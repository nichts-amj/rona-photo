"""Disposable offline UI verification. Never uses the user's photo history."""
import os
import sys
import tempfile
import threading
import subprocess
from pathlib import Path
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from local_engine import Studio
from web_app import make_server

if __name__=='__main__':
    output=Path('.cache/person-verify');output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='rona-area-test-',dir=output.resolve()) as temp:
        tempfile.tempdir=temp
        photo=Path(temp)/'portrait.png'
        with Image.open('web/launcher-retouch.png') as image:
            image.thumbnail((768,768));image.save(photo)
        server=make_server(0,Studio(root=Path(temp)/'history'))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        runtime=Path(os.environ['USERPROFILE'])/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node'
        env={**os.environ,'RONA_NODE_RUNTIME':str(runtime),'TEMP':temp,'TMP':temp}
        try:
            subprocess.run([str(runtime/'bin/node.exe'),sys.argv[1] if len(sys.argv)>1 else 'tests/retouch-area-browser.mjs',f'http://127.0.0.1:{server.server_port}',str(photo),str(output.resolve())],env=env,check=True)
        finally:server.shutdown();thread.join();server.server_close()
