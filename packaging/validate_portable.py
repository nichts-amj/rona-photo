import sys,os,json,threading,urllib.request,tempfile
from pathlib import Path
root=Path(sys.argv[1]).resolve();sys.path[:0]=[str(root/'app'),str(root)];os.environ['RONA_RESOURCE_DIR']=str(root)
import torch
torch.set_num_threads(2)
from pipeline.upscale import SwinIRX2
from pipeline.realesrgan import CompactRealESRGAN
from pipeline.swin2sr import Swin2SRCompressed
from pipeline.extra_models import ExtraModel
report={'loads':{},'python_is_bundled':Path(sys.executable).is_relative_to(root)}
for name,create in [('SwinIR',lambda:SwinIRX2('cpu')),('Real-ESRGAN',lambda:CompactRealESRGAN(.5,'cpu')),('Swin2SR',lambda:Swin2SRCompressed('cpu'))]+[(m,lambda m=m:ExtraModel(m,'cpu')) for m in ['H','F','G']]:
 engine=create()
 if isinstance(engine,ExtraModel):engine._load_restorer()
 report['loads'][name]='strict checkpoint load OK';engine.close();del engine;print(name,'OK',flush=True)
from local_engine import Studio
from web_app import make_server
with tempfile.TemporaryDirectory() as tmp:
 server=make_server(0,Studio(Path(tmp)));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
 try:
  url=f'http://127.0.0.1:{server.server_port}'
  for route in ['/','/api/bootstrap','/api/history','/rona.svg','/history.js']:
   with urllib.request.urlopen(url+route) as response:assert response.status==200
  report['http']='bootstrap, history, HTML, icon, JS OK'
 finally:server.shutdown();server.server_close();thread.join()
(root/'VALIDATION.txt').write_text(json.dumps(report,indent=2)+'\n\nValidated on development Windows host with bundled isolated Python. No browser interaction testing. Clean Windows machine without Python/CUDA Toolkit not tested. NVIDIA driver and Windows native runtime compatibility must be verified on destination machines.\n',encoding='utf-8')
print(json.dumps(report),flush=True)
