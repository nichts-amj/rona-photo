"""Development desktop entry: reuse the same loopback server and data as the browser."""
import argparse
import json
import secrets
import sys
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def emit(kind, **fields):
    print(json.dumps({'kind': kind, **fields}, ensure_ascii=False), flush=True)


def install_control(server, secret):
    """Only the owning desktop launcher can stop this server, and only when idle."""
    original = server.RequestHandlerClass

    class DesktopHandler(original):
        def do_POST(self):
            if self.path != '/api/desktop/stop':
                return super().do_POST()
            if not self.safe_host() or not secrets.compare_digest(self.headers.get('X-Desktop-Key', ''), secret):
                return self.send({'error': 'Tidak diizinkan'}, status=403)
            url = f'http://127.0.0.1:{self.server.server_port}/api/library/list'
            try:
                with urllib.request.urlopen(url, timeout=15) as response:
                    active = json.load(response).get('active', True)
            except Exception:
                return self.send({'error': 'Status pemrosesan belum dapat diperiksa.'}, status=503)
            if active:
                return self.send({'error': 'Tunggu pemrosesan selesai atau Cancel proses sebelum menutup aplikasi.'}, status=409)
            self.send({'ok': True})
            threading.Thread(target=server.shutdown, daemon=True).start()

    server.RequestHandlerClass = DesktopHandler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8772)
    args = parser.parse_args()
    emit('stage', text='Menyiapkan server lokal…')
    from web_app import make_server, check_existing_studio
    url = f'http://127.0.0.1:{args.port}'
    # Detect an existing browser server before creating services or claiming ownership.
    try:
        check_existing_studio(url)
    except (ConnectionError, OSError):
        pass
    else:
        emit('ready', url=url, owned=False)
        return
    emit('stage', text='Menyiapkan ruang kerja dan penyimpanan…')
    try:
        server = make_server(args.port)
    except OSError:
        check_existing_studio(url)
        emit('ready', url=url, owned=False)
        return
    secret = secrets.token_urlsafe(32)
    install_control(server, secret)
    url = f'http://127.0.0.1:{server.server_port}'
    emit('ready', url=url, owned=True, key=secret)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        emit('error', text=str(error))
        raise SystemExit(1)
