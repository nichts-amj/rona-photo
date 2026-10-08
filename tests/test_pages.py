"""Module routing preserves the legacy page and the existing processing API."""
import json
import threading
import unittest
import urllib.request
import test_studio
from test_studio import config
from web_app import make_server


class ModuleRoutingTests(unittest.TestCase):
    setUp = test_studio.StudioTests.setUp
    tearDown = test_studio.StudioTests.tearDown
    wait = test_studio.StudioTests.wait
    def test_module_routes_and_existing_processing(self):
        server=make_server(0,self.studio)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            for path,marker in [('/', 'Pilih modul Rona Photo'),('/retouch','/retouch/editor.mjs'),
                                ('/upscale','studio-v2.js'),('/index.html','studio-v2.js'),
                                ('/upscale/','studio-v2.js'),('/retouch/','/retouch/editor.mjs')]:
                with urllib.request.urlopen(base+path) as response:
                    self.assertIn(marker,response.read().decode())
                    if path.endswith('/') and path!='/':
                        self.assertEqual(response.url,base+path.rstrip('/'))
            for path in ['/style.css','/studio-v2.js','/history.js','/icons.svg','/launcher.css','/module-navigation.js','/rona.svg',
                         '/retouch/editor.css','/retouch/editor.mjs','/retouch/engine.mjs']:
                with urllib.request.urlopen(base+path) as response:
                    self.assertEqual(response.status,200)
                    self.assertTrue(response.read())
            with urllib.request.urlopen(base+'/api/bootstrap') as response:
                token=json.load(response)['token']
            request=urllib.request.Request(base+'/api/upload',data=test_studio.photo_bytes(),
                headers={'X-Studio-Token':token,'X-Filename':'routing.png','Content-Type':'image/png'})
            with urllib.request.urlopen(request) as response:
                uploaded=json.load(response)
            request=urllib.request.Request(base+'/api/jobs',
                data=json.dumps({'upload':uploaded['id'],'configs':[config(use_mask=False)]}).encode(),
                headers={'X-Studio-Token':token,'Content-Type':'application/json'})
            with urllib.request.urlopen(request) as response:
                jid=json.load(response)['id']
            result=self.wait(jid)
            self.assertEqual(result['status'],'done',result['error'])
            self.assertEqual(self.calls,[('A',.5),('B',.5)])
            with urllib.request.urlopen(base+result['results'][0]['url']) as response:
                self.assertEqual(response.status,200)
                self.assertTrue(response.read().startswith(b'\x89PNG'))
        finally:
            server.shutdown();server.server_close();thread.join()


