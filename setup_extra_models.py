"""Download official weights only, recording local integrity hashes and origins."""
import concurrent.futures
import hashlib
import json
import urllib.request
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path

ROOT=Path(__file__).resolve().parent
URLS={
 'codeformer.pth':'https://github.com/sczhou/CodeFormer/releases/download/v0.1.0/codeformer.pth',
 'GFPGANv1.4.pth':'https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth',
 'detection_Resnet50_Final.pth':'https://github.com/sczhou/CodeFormer/releases/download/v0.1.0/detection_Resnet50_Final.pth',
 'parsing_parsenet.pth':'https://github.com/sczhou/CodeFormer/releases/download/v0.1.0/parsing_parsenet.pth',
 'Real_HAT_GAN_SRx4.pth':'https://drive.usercontent.google.com/download?id=1Ma12vCWT27P9M99-s2RXnynKN-OQsBrv&export=download&confirm=t'}

class DownloadForm(HTMLParser):
    def __init__(self):
        super().__init__();self.action=None;self.fields={}
    def handle_starttag(self,tag,attrs):
        data=dict(attrs)
        if tag=='form':self.action=data.get('action')
        if tag=='input' and 'name' in data:self.fields[data['name']]=data.get('value','')

def fetch(entry):
    name,url=entry;path=ROOT/'models'/name
    if not path.exists():
        print('Download '+name,flush=True)
        response=urllib.request.urlopen(url,timeout=60)
        if 'text/html' in response.headers.get('Content-Type',''):
            form=DownloadForm();form.feed(response.read().decode())
            if not form.action or urllib.parse.urlsplit(form.action).hostname!='drive.usercontent.google.com':
                raise RuntimeError('Download did not return model weights: '+name)
            response=urllib.request.urlopen(form.action+'?'+urllib.parse.urlencode(form.fields),timeout=60)
        if 'text/html' in response.headers.get('Content-Type',''):
            raise RuntimeError('Unexpected HTML instead of weights: '+name)
        temp=path.with_suffix('.part')
        with temp.open('wb') as out:
            while block:=response.read(1024*1024):out.write(block)
        temp.replace(path)
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    print(name+' ready: '+str(path.stat().st_size),flush=True)
    return name,{'url':url,'sha256':digest,'bytes':path.stat().st_size}

def main():
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        manifest=dict(pool.map(fetch,URLS.items()))
    sources=json.loads((ROOT/'models/extra-sources.json').read_text())
    for item in sources.values():
        item['hashes']={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in item['files']}
    data={'weights':manifest,'sources':sources,'hash_note':'SHA256 locally recorded after official download, not author-published checksums.',
          'HAT_origin':'Official repository links to Drive folder 1HpmReFfoUqUbnAOQ7rvOeNU3uf_m69w0'}
    (ROOT/'models/extra-provenance.json').write_text(json.dumps(data,indent=2),encoding='utf-8')

if __name__=='__main__':main()
