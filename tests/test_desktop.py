import contextlib
import io
import json
import secrets
import os
import queue
import subprocess
import sys
import tempfile
from pathlib import Path
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

import test_studio
from desktop.backend import install_control, main
from web_app import make_server


class DesktopTests(unittest.TestCase):
    setUp = test_studio.StudioTests.setUp
    tearDown = test_studio.StudioTests.tearDown

    def test_existing_browser_server_is_reused(self):
        output = io.StringIO()
        with patch('sys.argv', ['desktop/backend.py']), patch('web_app.check_existing_studio', return_value={'app': 'rona-studio'}), patch('web_app.make_server') as factory, contextlib.redirect_stdout(output):
            main()
        factory.assert_not_called()
        result = json.loads(output.getvalue().splitlines()[-1])
        self.assertEqual(result, {'kind': 'ready', 'url': 'http://127.0.0.1:8772', 'owned': False})

    def test_old_browser_server_is_not_silently_replaced(self):
        with patch('sys.argv', ['desktop/backend.py']), patch('web_app.check_existing_studio', side_effect=RuntimeError('Versi lama')), patch('web_app.make_server') as factory, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'Versi lama'):
                main()
        factory.assert_not_called()

    def test_control_requires_secret_preserves_routes_and_refuses_busy_shutdown(self):
        server = make_server(0, self.studio)
        key = secrets.token_urlsafe(32)
        install_control(server, key)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'

        def stop(secret):
            request = urllib.request.Request(base + '/api/desktop/stop', data=b'', headers={'X-Desktop-Key': secret})
            return urllib.request.urlopen(request, timeout=10)

        try:
            for path in ['/', '/retouch', '/upscale', '/history']:
                with urllib.request.urlopen(base + path) as response:
                    self.assertEqual(response.status, 200)
            with self.assertRaises(urllib.error.HTTPError) as error:
                stop('wrong')
            self.assertEqual(error.exception.code, 403)
            self.studio.active = 'busy'
            with self.assertRaises(urllib.error.HTTPError) as error:
                stop(key)
            self.assertEqual(error.exception.code, 409)
            self.studio.active = None
            with stop(key) as response:
                self.assertEqual(json.load(response), {'ok': True})
            thread.join(3)
            self.assertFalse(thread.is_alive())
        finally:
            self.studio.active = None
            server.shutdown()
            server.server_close()
            thread.join()

    def test_real_worker_handshake_and_clean_shutdown(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            env = {**os.environ, 'RONA_DATA_DIR': folder, 'PYTHONIOENCODING': 'utf-8'}
            worker = subprocess.Popen([sys.executable, '-B', str(root/'desktop/backend.py'), '--port', '0'],
                                      cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True, encoding='utf-8')
            lines = queue.Queue()
            def read():
                for line in worker.stdout: lines.put(line)
            threading.Thread(target=read, daemon=True).start()
            try:
                for _ in range(8):
                    data = json.loads(lines.get(timeout=30))
                    if data['kind'] == 'ready': break
                    self.assertNotEqual(data['kind'], 'error', data)
                else: self.fail('No ready handshake')
                self.assertTrue(data['owned'])
                with urllib.request.urlopen(data['url']+'/api/bootstrap', timeout=15) as response:
                    self.assertEqual(json.load(response)['app'], 'rona-studio')
                request = urllib.request.Request(data['url']+'/api/desktop/stop', data=b'', headers={'X-Desktop-Key': data['key']})
                with urllib.request.urlopen(request, timeout=15) as response:
                    self.assertTrue(json.load(response)['ok'])
                self.assertEqual(worker.wait(timeout=15), 0)
            finally:
                if worker.poll() is None: worker.kill()
                worker.communicate(timeout=10)
