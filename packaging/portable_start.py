"""Isolated portable entry point; resources beside EXE, data per user."""
import os
import sys
from pathlib import Path
APP=Path(__file__).resolve().parent
ROOT=APP.parent
sys.path[:0]=[str(APP),str(ROOT)]
os.environ['RONA_RESOURCE_DIR']=str(ROOT)
os.environ.setdefault('RONA_DATA_DIR',str(Path(os.environ.get('LOCALAPPDATA',Path.home()))/'Rona Photo'/'studio'))
os.environ.setdefault('NUMBA_CACHE_DIR',str(Path(os.environ['RONA_DATA_DIR']).parent/'numba-cache'))
os.environ.setdefault('MPLCONFIGDIR',str(Path(os.environ['RONA_DATA_DIR']).parent/'matplotlib'))
import argparse
import json
import traceback

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8773)
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--cpu',action='store_true')
    args=parser.parse_args()
    if args.cpu:os.environ['CUDA_VISIBLE_DEVICES']=''
    import torch
    info={'cuda':False,'gpu':None,'reason':'GPU NVIDIA atau driver kompatibel tidak tersedia.'}
    try:
        if not args.cpu and torch.cuda.is_available():
            x=torch.ones(8,device='cuda');assert (x+x).sum().item()==16
            torch.cuda.synchronize();del x;torch.cuda.empty_cache()
            info.update(cuda=True,gpu=torch.cuda.get_device_name(0),reason='')
    except Exception as error:info['reason']='Pemeriksaan CUDA gagal: '+str(error)
    if args.cpu:info['reason']='Mode CPU dipilih.'
    from local_engine import Studio
    from pipeline.extra_models import availability,compatibility
    compatibility()
    data=Path(os.environ['RONA_DATA_DIR']);data.mkdir(parents=True,exist_ok=True)
    probe=data/'.write-check';probe.write_text('ok');probe.unlink()
    models=availability()
    if not all(models.values()):raise RuntimeError('Model belum lengkap: '+', '.join(k for k,v in models.items() if not v))
    if args.check:
        print(json.dumps({'product':'Rona Photo','version':'1.0','python':sys.version,'executable':sys.executable,'paths':sys.path,'torch':torch.__version__,'device':info,'models':models,'data':str(data)},indent=2));return
    from web_app import make_server
    studio=Studio();studio.device_info=info
    server=make_server(args.port,studio)
    print('Rona Photo v1.0 siap',flush=True)
    try:server.serve_forever()
    finally:server.server_close()

if __name__=='__main__':
    try:main()
    except Exception:
        traceback.print_exc();sys.exit(1)
