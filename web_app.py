"""Loopback-only web UI, served without extra web framework dependencies."""
import argparse
import hashlib
import json
import mimetypes
import os
import secrets
import threading
import webbrowser
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from local_engine import ROOT, Studio


def backend_revision():
    code=Path(__file__).resolve().parent
    files=[code/name for name in ('web_app.py','local_engine.py','history_store.py','unified_history.py')]
    for folder in ('retouch_backend','ai_edit_backend'):
        files.extend((code/folder).glob('*.py'))
        files.extend((code/folder).glob('*.json'))
    digest=hashlib.sha256()
    for path in sorted(files):
        if path.is_file():
            digest.update(str(path.relative_to(code)).encode());digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


BACKEND_REVISION=backend_revision()


def check_existing_studio(url):
    with urllib.request.urlopen(url+'/api/bootstrap',timeout=3) as response:data=json.load(response)
    if data.get('app')!='rona-studio':raise RuntimeError('Port digunakan aplikasi lain.')
    revision=data.get('backend_revision')
    if revision and revision!=BACKEND_REVISION:
        raise RuntimeError('Program Rona Photo versi lama masih berjalan. Selesaikan proses dan simpan foto, lalu tutup program lama dan jalankan kembali. Refresh browser saja tidak memuat perubahan backend.')
    # Older builds have no revision marker; verify the shared-history API explicitly.
    if not revision:
        try:
            with urllib.request.urlopen(url+'/api/library/list',timeout=10) as response:library=json.load(response)
            if not isinstance(library.get('items'),list):raise ValueError('Riwayat tidak tersedia.')
        except Exception as error:
            raise RuntimeError('Program lama belum mendukung Riwayat bersama. Tutup program Rona Photo yang masih berjalan, lalu jalankan kembali start-studio.cmd. Refresh browser saja tidak cukup.') from error
    return data


def make_server(port=0, studio=None):
    studio = studio or Studio()
    token = secrets.token_urlsafe(32)
    assets = ROOT/'web'
    from retouch_backend.api import RetouchAPI
    retouch_api = RetouchAPI(token,studio)
    from ai_edit_backend.api import AIEditAPI
    edit_api = AIEditAPI(token,studio)
    from unified_history import LibraryAPI
    library_api = LibraryAPI(studio,retouch_api.service,edit_api.service,token)
    gpu_dispatch = threading.RLock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def send(self, data, mime='application/json', status=200):
            if isinstance(data,(dict,list)):
                data = json.dumps(data,ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(data)))
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(data)

        def safe_host(self):
            return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

        def do_GET(self):
            if not self.safe_host():
                return self.send({'error':'Host tidak diizinkan'},status=403)
            path = unquote(urlsplit(self.path).path)
            try:
                if library_api.get(self,path):
                    return
                if edit_api.get(self,path):
                    return
                if retouch_api.get(self,path):
                    return
                if path=='/api/bootstrap':
                    from pipeline.extra_models import availability
                    return self.send({'app':'rona-studio','version':'1.0','product':'Rona Photo','backend_revision':BACKEND_REVISION,'device':getattr(studio,'device_info',None),'token':token,'presets':studio.presets(),'active':studio.active,
                                      'models':availability(),'uploads':[{'id':p['id'],'name':p['name'],'size':p['size'],
                                        'known_config':p['known_config'],'original':f'/files/{p["id"]}/original.png'} for p in studio.uploads.values()]})
                if path.startswith('/api/jobs/'):
                    return self.send(studio.status(path.rsplit('/',1)[-1]))
                if path=='/api/history':
                    return self.send(studio.history())
                if path.startswith('/api/history/'):
                    return self.send(studio.history_detail(path.rsplit('/',1)[-1]))
                if path=='/api/presets':
                    return self.send(studio.presets())
                # Canonical module URLs keep the existing relative Upscale assets working.
                if path in ('/upscale/', '/retouch/'):
                    self.send_response(302)
                    self.send_header('Location',path.rstrip('/') + ('?' + urlsplit(self.path).query if urlsplit(self.path).query else ''))
                    self.send_header('Content-Length','0')
                    self.end_headers()
                    return
                base = studio.root if path.startswith('/files/') else assets
                pages = {'/':'launcher.html','/upscale':'index.html','/retouch':'retouch.html','/history':'library.html'}
                rel = path[len('/files/'):] if path.startswith('/files/') else pages.get(path,path.lstrip('/'))
                target = (base/rel).resolve()
                if not target.is_relative_to(base.resolve()) or not target.is_file():
                    return self.send({'error':'Berkas tidak ditemukan'},status=404)
                self.send(target.read_bytes(),mimetypes.guess_type(target.name)[0] or 'application/octet-stream')
            except (ValueError,KeyError,OSError,TypeError) as e:
                self.send({'error':str(e)},status=400)

        def do_POST(self):
            if not self.safe_host() or self.headers.get('X-Studio-Token') != token:
                return self.send({'error':'Sesi tidak valid. Muat ulang halaman.'},status=403)
            origin = self.headers.get('Origin')
            if origin and origin != f'http://127.0.0.1:{self.server.server_port}':
                return self.send({'error':'Asal permintaan tidak diizinkan'},status=403)
            try:
                path = urlsplit(self.path).path
                if path in ('/api/jobs','/api/retouch/analyze','/api/retouch/preview','/api/retouch/apply','/api/retouch/segment','/api/ai-edit/preview','/api/ai-edit/apply'):
                    with gpu_dispatch:
                        if studio.active or retouch_api.service.active or edit_api.service.active:
                            return self.send({'error':{'code':'busy','message':'Proses foto lain masih berjalan. Tunggu atau Cancel terlebih dahulu.'}},status=409)
                        if path.startswith('/api/ai-edit/'):
                            studio.unload_engine()
                            retouch_api.service.manager.unload()
                            edit_api.post(self,path)
                            return
                        edit_api.service.manager.unload()
                        if path.startswith('/api/retouch/'):
                            studio.unload_engine()
                            retouch_api.post(self,path)
                            return
                        retouch_api.service.manager.unload()
                        length=int(self.headers.get('Content-Length','0'))
                        if not 0<length<=4*1024*1024:return self.send({'error':'Request terlalu besar atau kosong.'},status=413)
                        data=json.loads(self.rfile.read(length))
                        return self.send({'id':studio.start(data)})
                if library_api.post(self,path):
                    return
                if edit_api.post(self,path):
                    return
                if retouch_api.post(self,path):
                    return
                length = int(self.headers.get('Content-Length','0'))
                limit = 256*1024*1024 if path=='/api/upload' else 4*1024*1024
                if not 0<length<=limit:
                    return self.send({'error':'Berkas terlalu besar atau kosong (maks. unggah 256 MB).'},status=413)
                raw = self.rfile.read(length)
                if path=='/api/upload':
                    name = unquote(self.headers.get('X-Filename','foto.png'))
                    return self.send(studio.upload(raw,name))
                data = json.loads(raw)
                if path=='/api/history/edit':
                    return self.send(studio.history_edit(data))
                if path=='/api/history/delete':
                    return self.send(studio.history_delete(data))
                if path=='/api/jobs':
                    return self.send({'id':studio.start(data)})
                if path=='/api/cancel':
                    studio.cancel(data['id'])
                    return self.send({'ok':True})
                if path=='/api/presets':
                    return self.send(studio.save_preset(data['name'],data['configs']))
                if path=='/api/presets/delete':
                    return self.send(studio.delete_preset(data['id']))
                if path=='/api/open-folder':
                    state = studio.status(data['id'])
                    if state['status']!='done':
                        raise ValueError('Hasil belum selesai.')
                    folder = studio.root/state['upload']/state['id']
                    os.startfile(str(folder))
                    return self.send({'ok':True})
                return self.send({'error':'Alamat tidak ditemukan'},status=404)
            except (ValueError,KeyError,TypeError,OSError) as error:
                self.send({'error':str(error)},status=400)

    class LocalServer(ThreadingHTTPServer):
        def server_close(self):
            studio.close()
            retouch_api.service.close()
            edit_api.service.close()
            super().server_close()
    return LocalServer(('127.0.0.1',port),Handler)


def main():
    parser = argparse.ArgumentParser(description='AI Photo Retouch · Studio lokal')
    parser.add_argument('--port',type=int,default=8772)
    parser.add_argument('--no-browser',action='store_true')
    args = parser.parse_args()
    try:
        server = make_server(args.port)
    except OSError:
        url=f'http://127.0.0.1:{args.port}'
        try:
            check_existing_studio(url)
        except RuntimeError as error:
            raise SystemExit(str(error)) from None
        except Exception:
            raise SystemExit('Tidak dapat membuka studio pada port tersebut. Periksa program yang masih berjalan.') from None
        if not args.no_browser:webbrowser.open(url)
        print('Studio yang sudah berjalan dibuka kembali: '+url)
        return
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'Studio lokal siap: {url}',flush=True)
    print('Biarkan program berjalan saat mengolah foto. Ctrl+C untuk menutup.',flush=True)
    if not args.no_browser:
        threading.Timer(0.5,lambda:webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__=='__main__':
    main()
