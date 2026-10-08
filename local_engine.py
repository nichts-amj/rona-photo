"""Single-worker local studio. Models run sequentially; exact settings key the cache."""
import os
import copy
import hashlib
import json
import math
import shutil
import threading
import time
import uuid
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from pipeline.io import read_photo, save_png, sha256
from pipeline.fusion import fuse, make_alpha

from resource_paths import ROOT
NAMES = {'A':'SwinIR', 'B':'Real-ESRGAN', 'S':'Swin2SR', 'H':'HAT', 'F':'codeFormer', 'G':'GFPGAN'}


def write_json(path, data):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    temp.replace(path)


def number(value, low, high):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'Nilai harus di antara {low} dan {high}.')
    return value


def config_valid(raw):
    weights = {key:float(number(raw.get('weights',{}).get(key,0),0,100)) for key in NAMES}
    if sum(weights.values()) <= 0:
        raise ValueError('Pilih minimal satu model dengan kontribusi lebih dari nol.')
    reference = raw.get('reference','A')
    if reference not in NAMES:
        raise ValueError('Model perlindungan tidak dikenal.')
    tile = raw.get('tile',128)
    overlap = raw.get('overlap',32)
    b_tile = raw.get('b_tile',256)
    if tile not in (64,96,128,192,256) or overlap not in (0,8,16,24,32,48,64) or overlap >= tile or b_tile not in (64,128,256,512):
        raise ValueError('Kombinasi ukuran potongan/overlap tidak valid.')
    device = raw.get('device','cuda')
    if device not in ('cuda','cpu'):
        raise ValueError('Perangkat tidak valid.')
    label = str(raw.get('label','Konfigurasi'))[:80]
    face = raw.get('face_model','')
    if face not in ('','F','G') or reference not in ('A','B','S','H'):
        raise ValueError('Pilihan model wajah/acuan tidak valid.')
    selected = [m for m,w in weights.items() if w>0]
    if any(m in ('F','G') for m in selected) and (len(selected)!=1 or face):
        raise ValueError('Pada gabungan, pilih CodeFormer/GFPGAN melalui opsi restorasi wajah.')
    h_tile=raw.get('h_tile',64)
    if h_tile not in (64,96,128):
        raise ValueError('Ukuran potongan HAT tidak valid.')
    label_models=list(selected)
    if raw.get('use_mask',True) and not any(m in ('F','G') for m in selected) and reference not in label_models:
        label_models.insert(0,reference)
    label=' + '.join(NAMES[m] for m in label_models)
    if face:
        label+=' · Wajah: '+NAMES[face]
    scale = raw.get('output_scale',2)
    if isinstance(scale,bool) or scale not in (2,4):
        raise ValueError('Skala keluaran harus 2 atau 4.')
    if scale==4 and ('A' in selected or any(m in ('F','G') for m in selected) or (raw.get('use_mask',True) and reference=='A')):
        raise ValueError('Konfigurasi dengan SwinIR atau model wajah tunggal hanya mendukung 2x.')
    return {'output_scale':scale,'label':label,'weights':weights,'reference':reference,'tile':tile,'overlap':overlap,
            'b_tile':b_tile,'denoise':float(number(raw.get('denoise',0.5),0,1)),
            'feather':int(number(raw.get('feather',10),0,32)),'device':device,
            'use_mask':bool(raw.get('use_mask',True)) and not any(m in ('F','G') for m in selected),
            'h_tile':h_tile,'face_model':face,'gpu_optimization':bool(raw.get('gpu_optimization',True)),
            'fidelity':float(number(raw.get('fidelity',0.8),0,1)),
            'face_mix':float(number(raw.get('face_mix',0.7),0,1))}


def regions_valid(regions, size):
    if not isinstance(regions,list) or len(regions)>4000:
        raise ValueError('Terlalu banyak penandaan; kurangi goresan.')
    checked = []
    for region in regions:
        points = region.get('polygon')
        if not isinstance(points,list) or not 3 <= len(points) <= 200:
            raise ValueError('Poligon area tidak valid.')
        checked.append({'polygon':[[number(p[0],0,size[0]),number(p[1],0,size[1])] for p in points]})
    return checked


class Cancelled(Exception):
    pass


def manual_alpha(size,regions,feather,scale=2):
    """Union brush marks before blur; cost does not grow with stroke count."""
    image=Image.new('L',size,0);draw=ImageDraw.Draw(image)
    for region in regions:
        draw.polygon([(round(x*scale),round(y*scale)) for x,y in region['polygon']],fill=255)
    core=np.asarray(image)==255
    radius=feather*scale
    expanded=image.filter(ImageFilter.MaxFilter(2*radius+1)) if radius else image
    alpha=1-np.asarray(expanded.filter(ImageFilter.GaussianBlur(radius)),dtype=np.float32)/255
    alpha[core]=0
    return alpha,core


from history_store import HistoryMixin


class Studio(HistoryMixin):
    def __init__(self, root=None, infer=None):
        self.root = Path(root or os.environ.get('RONA_DATA_DIR') or ROOT/'outputs/studio').resolve()
        self.root.mkdir(parents=True,exist_ok=True)
        self.uploads = {}
        self.jobs = {}
        self.lock = threading.RLock()
        self.active = None
        self.infer_override = infer
        self.engine_lock = threading.RLock()
        self.engine = None
        self.engine_key = None

    def upload(self, data, name):
        with self.lock:
            return self._upload(data, name)

    def _upload(self, data, name):
        uid = uuid.uuid4().hex
        folder = self.root/uid
        folder.mkdir()
        suffix = Path(name).suffix.lower()
        if suffix not in ('.jpg','.jpeg','.png','.webp'):
            raise ValueError('Pilih foto JPG, PNG, atau WebP.')
        source = folder/('source'+suffix)
        source.write_bytes(data)
        with Image.open(source) as im:
            if im.width*im.height>50_000_000:
                raise ValueError('Batas saat ini 50 megapiksel; foto tidak diperkecil otomatis.')
        image, metadata = read_photo(source)
        save_png(image,folder/'original.png')
        config = None
        try:
            from pipeline.hybrid_run import resolve_regions
            config = resolve_regions(metadata['source_sha256'],image.size)
        except ValueError:
            pass
        item = {'id':uid,'name':name[:150],'size':list(image.size),'source':metadata,
                'known_config':config,'folder':folder}
        with self.lock:
            self.uploads[uid] = item
            write_json(folder/'upload.json',self._public_photo(item)|{'created':time.time()})
        public = {k:v for k,v in item.items() if k not in ('folder','source')}
        public['warnings'] = metadata['warnings']
        public['original'] = f'/files/{uid}/original.png'
        return public

    def presets(self):
        path = self.root/'presets.json'
        with self.lock:
            return json.loads(path.read_text(encoding='utf-8')) if path.exists() else []

    def save_preset(self, name, configs):
        name = str(name).strip()[:80]
        if not name:
            raise ValueError('Nama preset diperlukan.')
        if not isinstance(configs,list) or not 1<=len(configs)<=2:
            raise ValueError('Satu atau dua konfigurasi diperlukan.')
        configs = [config_valid(c) for c in configs]
        with self.lock:
            presets = self.presets()
            presets = [p for p in presets if p['name'] != name]
            if len(presets)>=100:
                raise ValueError('Maksimal 100 preset.')
            presets.append({'id':uuid.uuid4().hex,'name':name,'configs':configs})
            write_json(self.root/'presets.json',presets)
        return presets

    def delete_preset(self, pid):
        with self.lock:
            presets = [p for p in self.presets() if p['id'] != pid]
            write_json(self.root/'presets.json',presets)
        return presets

    def start(self, request):
        if 'items' in request:
            return self.start_batch(request)
        with self.lock:
            if self.active:
                raise ValueError('Masih ada proses berjalan. Tunggu atau batalkan terlebih dahulu.')
            uid = request.get('upload')
            if uid not in self.uploads:
                self.restore_upload(uid)
            configs = request.get('configs',[])
            if not isinstance(configs,list) or not 1<=len(configs)<=2:
                raise ValueError('Pilih satu atau dua konfigurasi.')
            configs = [config_valid(c) for c in configs]
            regions = regions_valid(request.get('regions',[]),self.uploads[uid]['size'])
            jid = uuid.uuid4().hex
            job = {'id':jid,'upload':uid,'status':'running','stage':'Menyiapkan foto','percent':0,
                   'configs':configs,'results':[],'error':None,'regions':regions,
                   'use_known':bool(request.get('use_known',False)),'cancel':threading.Event()}
            self.jobs[jid] = job
            self.active = jid
            threading.Thread(target=self._run,args=(job,),daemon=True).start()
            return jid

    def start_batch(self, request):
        with self.lock:
            if self.active:
                raise ValueError('Masih ada proses berjalan.')
            items=request.get('items')
            if not isinstance(items,list) or not 1<=len(items)<=10:
                raise ValueError('Batch berisi 1–10 foto.')
            children=[]
            for item in items:
                uid=item.get('upload')
                if uid not in self.uploads:
                    self.restore_upload(uid)
                configs=item.get('configs',[])
                if not isinstance(configs,list) or not 1<=len(configs)<=2:
                    raise ValueError('Pilih satu atau dua konfigurasi per foto.')
                children.append({'id':uuid.uuid4().hex,'upload':uid,'status':'waiting','stage':'Menunggu',
                    'name':self.uploads[uid]['name'],'percent':0,'configs':[config_valid(c) for c in configs],
                    'results':[],'error':None,'regions':regions_valid(item.get('regions',[]),self.uploads[uid]['size']),
                    'use_known':bool(item.get('use_known',False))})
            jid=uuid.uuid4().hex
            event=threading.Event()
            parent={'id':jid,'status':'running','stage':'Menyiapkan antrean','percent':0,'batch':True,
                    'cancel':event,'items':children,'results':[],'error':None}
            for child in children:
                child['cancel']=event
                child['parent']=jid
                self.jobs[child['id']]=child
            self.jobs[jid]=parent
            self.active=jid
            threading.Thread(target=self._run_batch,args=(parent,),daemon=True).start()
            return jid

    def _run_batch(self,parent):
        try:
            for index,child in enumerate(parent['items']):
                if parent['cancel'].is_set():
                    self.update(child,status='cancelled',stage='Dibatalkan')
                    continue
                self.update(parent,stage=f'Foto {index+1}/{len(parent["items"])} · {child["name"]}')
                self.update(child,status='running')
                self._run(child)
                self.update(parent,percent=round(100*(index+1)/len(parent['items'])))
            self.update(parent,status='cancelled' if parent['cancel'].is_set() else 'done',stage='Antrean selesai')
        finally:
            self.unload_engine()
            with self.lock:
                self.active=None

    def status(self,jid):
        with self.lock:
            if jid not in self.jobs:
                raise ValueError('Proses tidak ditemukan.')
            def public(job):
                result={k:v for k,v in job.items() if k not in ('cancel','regions','items')}
                if 'items' in job:
                    result['items']=[public(c) for c in job['items']]
                    children=result['items']
                    if children:
                        # Completed failures consume their queue slot; cancelled items do not.
                        result['percent']=round(sum(100 if c['status'] in ('done','failed') else c['percent'] for c in children)/len(children))
                return result
            return copy.deepcopy(public(self.jobs[jid]))

    def cancel(self,jid):
        with self.lock:
            if jid not in self.jobs:
                raise ValueError('Proses tidak ditemukan.')
            self.jobs[jid]['cancel'].set()

    def update(self,job,**kwargs):
        with self.lock:
            job.update(kwargs)

    def check(self,job):
        if job['cancel'].is_set():
            raise Cancelled('Dibatalkan pengguna.')

    def _settings(self,model,c):
        settings = {'model':model,'device':c['device'],'version':1}
        if model in ('B','S','H') and c['device']=='cuda' and c.get('gpu_optimization',True):
            settings.update(version=2,gpu_optimization='mixed-precision-adaptive-v1')
        if c.get('output_scale',2)!=2:
            settings['output_scale']=c['output_scale']
        if model in ('F','G'):
            settings.update(fidelity=c['fidelity'] if model=='F' else None)
        elif model=='H':
            settings.update(tile=c['h_tile'])
        elif model=='B':
            settings.update(tile=c['b_tile'],denoise=c['denoise'])
        else:
            settings.update(tile=c['tile'],overlap=c['overlap'])
        return settings

    def _known_cached(self,item,model,settings):
        if settings['version']!=1 or settings.get('output_scale',2)!=2 or model not in ('A','B','S'):
            return None
        defaults = settings['device']=='cuda' and settings['tile']==(256 if model=='B' else 128)
        defaults = defaults and (settings.get('denoise')==0.5 if model=='B' else settings.get('overlap')==32)
        batch = ROOT/'outputs/batch-20260929-three-model2'
        if not defaults or not (batch/'experiment.json').exists():
            return None
        manifest = json.loads((batch/'experiment.json').read_text(encoding='utf-8'))
        for row in manifest['entries']:
            if row['source']['source_sha256']==item['source']['source_sha256']:
                path = batch/row['id']/manifest['files'][model]
                if path.exists() and sha256(path)==row['files'][path.name]:
                    return path
        return None

    def unload_engine(self):
        with self.engine_lock:
            engine=self.engine
            self.engine=None
            self.engine_key=None
            if engine is not None:
                engine.close()

    def close(self):
        with self.lock:
            if self.active and self.active in self.jobs:
                self.jobs[self.active]['cancel'].set()
        self.unload_engine()

    def _make_engine(self,model,c):
        if model in ('H','F','G'):
            from pipeline.extra_models import ExtraModel
            return ExtraModel(model,c['device'])
        if model=='A':
            from pipeline.upscale import SwinIRX2
            return SwinIRX2(c['device'])
        if model=='B':
            from pipeline.realesrgan import CompactRealESRGAN
            return CompactRealESRGAN(c['denoise'],c['device'])
        from pipeline.swin2sr import Swin2SRCompressed
        return Swin2SRCompressed(c['device'])

    def _infer(self,model,image,c,progress):
        if self.infer_override:
            return self.infer_override(model,image,c,progress)
        with self.engine_lock:
            key=(model,c['device'],c.get('denoise') if model=='B' else None,c.get('gpu_optimization',True))
            reused=self.engine is not None and self.engine_key==key
            load_start=time.perf_counter()
            if not reused:
                self.unload_engine()
                self.engine=self._make_engine(model,c)
                self.engine_key=key
            load_seconds=time.perf_counter()-load_start if not reused else 0.0
            engine=self.engine
            engine.gpu_optimization=c.get('gpu_optimization',True)
            infer_start=time.perf_counter()
            try:
                if model in ('H','F','G'):
                    result,info=engine.infer(image,c,progress)
                elif model=='A':
                    result,info=engine.infer(image,c['tile'],c['overlap'],progress)
                elif model=='B':
                    result,info=engine.infer(image,c['b_tile'],progress,output_scale=c['output_scale'])
                else:
                    result,info=engine.infer(image,progress=progress,tile=c['tile'],overlap=c['overlap'],output_scale=c['output_scale'])
                info.update(engine_reused=reused,engine_setup_seconds=load_seconds,
                            model_run_seconds=time.perf_counter()-infer_start)
                if reused:
                    info['model_load_seconds']=0.0
                return result,info
            except Exception:
                self.unload_engine()
                raise
            finally:
                if model not in ('B','S','H'):
                    self.unload_engine()

    def _run(self,job):
        start = time.perf_counter()
        item = self.uploads[job['upload']]
        folder = item['folder']/job['id']
        folder.mkdir()
        try:
            image,source = read_photo(Path(item['source']['source_path']))
            timings={'source_read_seconds':time.perf_counter()-start,'model_png_save_seconds':0.0,'result_png_save_seconds':0.0}
            if source['source_sha256'] != item['source']['source_sha256']:
                raise ValueError('Foto sumber berubah; unggah ulang.')
            mask_config = item['known_config'] if job['use_known'] else None
            # All required models, including the protected reference, are deduplicated.
            needed = {}
            plan = []
            for c in job['configs']:
                keys = {}
                selected = [m for m,w in c['weights'].items() if w>0]
                if c['face_model']:
                    selected.append(c['face_model'])
                use_mask = c['use_mask'] and (job['regions'] or mask_config)
                if use_mask and c['reference'] not in selected:
                    selected.append(c['reference'])
                for model in selected:
                    settings = self._settings(model,c)
                    key = hashlib.sha256(json.dumps(settings,sort_keys=True).encode()).hexdigest()[:24]
                    needed[key] = (model,c,settings)
                    keys[model] = key
                plan.append(keys)
            cache = item['folder']/'cache'
            cache.mkdir(exist_ok=True)
            stats = {}
            for index,(key,(model,c,settings)) in enumerate(needed.items()):
                self.check(job)
                dest = cache/(key+'.png')
                meta = cache/(key+'.json')
                reused = False
                record = {}
                if dest.exists() and meta.exists():
                    record = json.loads(meta.read_text())
                    reused = record['sha256']==sha256(dest)
                    if model in ('F','G'):
                        reused=reused and all((cache/(key+suffix)).exists() and sha256(cache/(key+suffix))==record.get('aux',{}).get(suffix) for suffix in ('_face.png','_transmission.png'))
                if not reused:
                    old = self._known_cached(item,model,settings)
                    if old:
                        shutil.copyfile(old,dest)
                        reused = True
                if reused:
                    self.update(job,stage=f'Memakai hasil tersimpan {NAMES[model]}')
                    info = {**record.get('info',{}),'reused':True,'settings':settings}
                else:
                    self.update(job,stage=f'Memuat {NAMES[model]} ({index+1}/{len(needed)})')
                    def progress(done,total,tile):
                        self.check(job)
                        self.update(job,stage=f'{NAMES[model]} · potongan {done}/{total}',
                                    percent=round(90*(index+done/total)/len(needed)))
                    result,info = self._infer(model,image,c,progress)
                    self.check(job)
                    if result.size!=(image.width*c['output_scale'],image.height*c['output_scale']):
                        raise ValueError('Ukuran hasil model tidak sesuai.')
                    face_layer=info.pop('_face_layer',None)
                    transmission=info.pop('_transmission',None)
                    if face_layer is not None:
                        save_png(face_layer,cache/(key+'_face.png'))
                        save_png(transmission,cache/(key+'_transmission.png'))
                    save_start=time.perf_counter()
                    save_png(result,dest)
                    info['png_save_seconds']=time.perf_counter()-save_start
                    timings['model_png_save_seconds']+=info['png_save_seconds']
                    del result
                    info = {**info,'reused':False,'settings':settings}
                aux={suffix:sha256(cache/(key+suffix)) for suffix in ('_face.png','_transmission.png')} if model in ('F','G') else {}
                write_json(meta,{'sha256':sha256(dest),'settings':settings,'info':info,'aux':aux})
                stats[key] = info
            self.update(job,stage='Menggabungkan hasil dan memeriksa berkas',percent=92)
            merge_start=time.perf_counter()
            results = []
            for index,(c,keys) in enumerate(zip(job['configs'],plan)):
                self.check(job)
                selected = [m for m,w in c['weights'].items() if w>0]
                images = {}
                for m,k in keys.items():
                    with Image.open(cache/(k+'.png')) as im:
                        images[m] = im.convert('RGB')
                weight_sum = sum(c['weights'].values())
                output = np.zeros((image.height*c['output_scale'],image.width*c['output_scale'],3),dtype=np.uint8)
                arrays = {m:np.asarray(im) for m,im in images.items()}
                for y in range(0,output.shape[0],128):
                    self.check(job)
                    block = sum(arrays[m][y:y+128].astype(np.float32)*(c['weights'][m]/weight_sum) for m in selected)
                    output[y:y+128] = np.rint(block).clip(0,255).astype(np.uint8)
                combined = Image.fromarray(output)
                exact = None
                if c['use_mask']:
                    protected_regions = []
                    # Known C has nonuniform candidate regions; preserve that exact recipe for A/B.
                    if mask_config and set(selected)<= {'A','B'} and c['reference']=='A' and 'A' in images and 'B' in images:
                        mask = copy.deepcopy(mask_config)
                        mask['base_candidate_weight'] = c['weights']['B']/weight_sum
                        for r in mask['protected_regions']:
                            r['feather'] = c['feather']
                        alpha,core = make_alpha(combined.size,mask,scale=c['output_scale'])
                        combined = fuse(images['A'],images['B'],alpha)
                    else:
                        if mask_config:
                            protected_regions.extend(copy.deepcopy(mask_config['protected_regions']))
                        alpha,core = make_alpha(combined.size,{'base_candidate_weight':1,'protected_regions':protected_regions},scale=c['output_scale'])
                        if protected_regions:
                            combined = fuse(images[c['reference']],combined,alpha)
                    if job['regions']:
                        manual,manual_core=manual_alpha(combined.size,job['regions'],c['feather'],scale=c['output_scale'])
                        combined=fuse(images[c['reference']],combined,manual)
                        alpha*=manual
                        core|=manual_core
                    if core.any():
                        exact = bool(np.array_equal(np.asarray(combined)[core],arrays[c['reference']][core]))
                        if not exact:
                            raise RuntimeError('Verifikasi area perlindungan gagal.')
                face_model=c['face_model'] or (selected[0] if selected[0] in ('F','G') else '')
                if face_model:
                    fkey=keys[face_model]
                    with Image.open(cache/(fkey+'_face.png')) as im:
                        foreground=np.asarray(im,dtype=np.float32)
                    with Image.open(cache/(fkey+'_transmission.png')) as im:
                        transmission=np.asarray(im,dtype=np.float32)/255
                    base=np.asarray(image.resize(combined.size,Image.Resampling.LANCZOS) if selected[0] in ('F','G') else combined,dtype=np.float32)
                    mix=c['face_mix']
                    restored=foreground+base*transmission
                    combined=Image.fromarray(np.rint(base*(1-mix)+restored*mix).clip(0,255).astype(np.uint8))
                    # Protected regions remain protected even with optional face restoration.
                    if c['use_mask'] and (job['regions'] or mask_config):
                        combined=fuse(images[c['reference']],combined,alpha)
                        if core.any() and not np.array_equal(np.asarray(combined)[core],arrays[c['reference']][core]):
                            raise RuntimeError('Perlindungan area setelah restorasi wajah gagal.')
                    del foreground,transmission,base,restored
                filename = f'result_{index+1}.png'
                save_start=time.perf_counter()
                save_png(combined,folder/filename)
                timings['result_png_save_seconds']+=time.perf_counter()-save_start
                results.append({'label':c['label'],'url':f'/files/{item["id"]}/{job["id"]}/{filename}',
                                'sha256':sha256(folder/filename),'size':list(combined.size),
                                'protected_exact':exact,'output_scale':c['output_scale']})
                del images,arrays,combined,output
            self.check(job)
            if sha256(Path(source['source_path']))!=source['source_sha256']:
                raise ValueError('Sumber berubah saat pemrosesan.')
            timings['merge_read_verify_seconds']=time.perf_counter()-merge_start-timings['result_png_save_seconds']
            manifest = {'timings':timings,'source':source,'configs':job['configs'],'regions':job['regions'],
                        'known_mask_config':mask_config,'results':results,'models':stats,
                        'seconds':time.perf_counter()-start,'sequential':True,'scale':job['configs'][0]['output_scale'] if len({c['output_scale'] for c in job['configs']})==1 else None}
            write_json(folder/'processing.json',manifest)
            write_json(item['folder']/'mask.json',{'source_sha256':source['source_sha256'],
                        'regions':job['regions'],'use_known':job['use_known']})
            self.update(job,status='done',stage='Hasil siap',percent=100,results=results,
                        seconds=manifest['seconds'],reused=sum(s['reused'] for s in stats.values()),
                        model_runs=len(stats),manifest=f'/files/{item["id"]}/{job["id"]}/processing.json')
        except Cancelled:
            self.update(job,status='cancelled',stage='Proses dibatalkan')
        except Exception as error:
            write_json(folder/'failure.json',{'error':str(error)})
            self.update(job,status='failed',stage='Pemrosesan gagal',error=str(error))
        finally:
            with self.lock:
                if 'parent' not in job:
                    self.unload_engine()
                    self.active = None
