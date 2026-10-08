"""Retouch owns model instances; Upscale utilities/weights are read-only."""
import gc
import hashlib
import importlib
import json
import sys
import threading
import time
from pathlib import Path
from resource_paths import ROOT


class RetouchError(RuntimeError):
    def __init__(self,code,message):super().__init__(message);self.code=code


class ModelManager:
    def __init__(self,config,loader=None):
        self.config=config;self.loader=loader or self._load;self.cached=None;self.role=None
        self.device=None;self.loading=None;self.fallback=None;self.last_used=0;self.lock=threading.RLock()
        self.verified=set();self.timer=None

    def choose_device(self):
        if self.device is None:
            import torch
            requested=self.config['device']
            self.device='cuda' if requested!='cpu' and torch.cuda.is_available() else 'cpu'
        return self.device

    def status(self):
        return {'device':self.device or 'auto','loading':self.loading,'loaded':[self.role] if self.cached is not None else [],'fallback':self.fallback}

    def unload(self):
        with self.lock:
            self.cached=None;self.role=None;gc.collect()
            if self.device=='cuda':
                import torch
                torch.cuda.empty_cache()

    def _idle(self):
        with self.lock:
            if time.monotonic()-self.last_used>=self.config.get('idle_unload_seconds',120):self.unload()

    def get(self,role):
        device=self.choose_device()
        if self.role!=role or self.cached is None:
            self.unload();self.loading=role
            try:self.cached=self.loader(role,device);self.role=role
            except Exception as error:
                self.cached=None;self.role=None
                if isinstance(error,RetouchError):raise
                raise RetouchError('model_load','Model Retouch gagal dimuat: '+str(error)) from error
            finally:self.loading=None
        self.last_used=time.monotonic();return self.cached

    def run(self,role,action):
        with self.lock:
            if self.timer:self.timer.cancel()
            try:
                try:return action(self.get(role))
                except Exception as error:
                    oom='out of memory' in str(error).lower() or 'cuda' in str(error).lower()
                    if self.device=='cuda' and self.config['device']=='auto' and oom:
                        self.unload();self.device='cpu';self.fallback='GPU tidak tersedia atau kehabisan memori; proses diulang pada CPU.'
                        return action(self.get(role))
                    if isinstance(error,RetouchError):raise
                    raise RetouchError('inference','Inference Retouch gagal: '+str(error)) from error
            finally:
                self.last_used=time.monotonic();self.timer=threading.Timer(self.config.get('idle_unload_seconds',120),self._idle);self.timer.daemon=True;self.timer.start()

    def weight(self,name):
        path=ROOT/'models'/name
        if not path.is_file():raise RetouchError('missing_model',f'Bobot {name} belum tersedia. Pasang bobot secara eksplisit; tidak ada unduhan otomatis.')
        if name not in self.verified:
            if name=='deeplabv3_mobilenet_v3_large-fc3c493d.pth':
                expected=json.loads((ROOT/'models/person-provenance.json').read_text())['sha256']
            else:expected=json.loads((ROOT/'models/extra-provenance.json').read_text())['weights'][name]['sha256']
            digest=hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
            if digest.hexdigest()!=expected:raise RetouchError('model_integrity','Integritas bobot Retouch tidak cocok: '+name)
            self.verified.add(name)
        return path

    def _load(self,role,device):
        import torch
        # Existing generic compatibility shim and file importer only; never ExtraModel.
        from pipeline.extra_models import compatibility,load_module
        compatibility()
        if role=='person':
            from torchvision.models.segmentation import deeplabv3_mobilenet_v3_large
            model=deeplabv3_mobilenet_v3_large(weights=None,weights_backbone=None,num_classes=21,aux_loss=True)
            state=torch.load(self.weight('deeplabv3_mobilenet_v3_large-fc3c493d.pth'),map_location='cpu',weights_only=True)
        elif role=='detector':
            if self.config['face_detector']!='retinaface_resnet50':raise RetouchError('config','Adapter detector belum tersedia.')
            from facexlib.detection.retinaface import RetinaFace
            model=RetinaFace(network_name='resnet50',half=False,device=torch.device(device))
            state=torch.load(self.weight('detection_Resnet50_Final.pth'),map_location='cpu',weights_only=True)
            state={k.removeprefix('module.'):v for k,v in state.items()}
        elif role=='parser':
            if self.config['face_parser']!='parsenet':raise RetouchError('config','Adapter parser belum tersedia.')
            from facexlib.parsing.parsenet import ParseNet
            model=ParseNet(in_size=512,out_size=512,parsing_ch=19)
            state=torch.load(self.weight('parsing_parsenet.pth'),map_location='cpu',weights_only=True)
        elif role=='restorer' or role.startswith('restorer:'):
            name=role.split(':',1)[1] if ':' in role else self.config['face_restorer']
            if name=='codeformer':
                load_module('basicsr.archs.vqgan_arch',ROOT/'third_party/codeformer/vqgan_arch.py')
                module=load_module('third_party.codeformer.codeformer_arch',ROOT/'third_party/codeformer/codeformer_arch.py')
                model=module.CodeFormer(dim_embd=512,codebook_size=1024,n_head=8,n_layers=9,connect_list=['32','64','128','256'])
                state=torch.load(self.weight('codeformer.pth'),map_location='cpu',weights_only=True)['params_ema']
            elif name=='gfpgan':
                import third_party.gfpgan
                module=load_module('third_party.gfpgan.gfpganv1_clean_arch',ROOT/'third_party/gfpgan/gfpganv1_clean_arch.py')
                model=module.GFPGANv1Clean(out_size=512,num_style_feat=512,channel_multiplier=2,decoder_load_path=None,fix_decoder=False,num_mlp=8,input_is_latent=True,different_w=True,narrow=1,sft_half=True)
                state=torch.load(self.weight('GFPGANv1.4.pth'),map_location='cpu',weights_only=True)['params_ema']
            else:raise RetouchError('config','Adapter restorasi belum tersedia.')
        else:raise RetouchError('config','Peran model tidak valid.')
        model.load_state_dict(state,strict=True);del state
        return model.eval().to(device)


class FaceDetector:
    def __init__(self,manager):self.manager=manager
    def detectFaces(self,rgb,edge=1024,max_faces=16):
        import cv2,numpy as np,torch
        h,w=rgb.shape[:2];scale=min(1,edge/max(h,w));small=cv2.resize(rgb,(max(1,round(w*scale)),max(1,round(h*scale))))
        def run(model):
            with torch.inference_mode():return model.detect_faces(small[:,:,::-1].copy(),conf_threshold=.8,use_origin_size=True)
        rows=self.manager.run('detector',run);faces=[]
        for row in rows[:max_faces]:
            landmarks=(row[5:15].reshape(5,2)/scale).astype(np.float32)
            if np.linalg.norm(landmarks[0]-landmarks[1])<4:continue
            bbox=(row[:4]/scale).tolist();bbox=[max(0,bbox[0]),max(0,bbox[1]),min(w,bbox[2]),min(h,bbox[3])]
            faces.append({'bbox':bbox,'confidence':float(row[4]),'landmarks':landmarks.tolist()})
        return faces


class FaceParser:
    def __init__(self,manager):self.manager=manager
    def createFaceMask(self,rgb,faces):
        import cv2,numpy as np,torch
        template=np.array([[192.98138,239.94708],[318.90277,240.1936],[256.63416,314.01935],[201.26117,371.41043],[313.08905,371.15118]],np.float32)
        aligned=[]
        for face in faces:
            matrix,_=cv2.estimateAffinePartial2D(np.array(face['landmarks'],np.float32),template,method=cv2.LMEDS)
            if matrix is None:raise RetouchError('segmentation','Landmark tidak dapat dipetakan ke mask wajah.')
            crop=cv2.warpAffine(rgb,matrix,(512,512),borderMode=cv2.BORDER_REFLECT_101)
            aligned.append({**face,'matrix':matrix,'aligned':crop})
        def parse(model):
            for face in aligned:
                tensor=torch.from_numpy(np.ascontiguousarray(face['aligned'].transpose(2,0,1))).float().unsqueeze(0).to(self.manager.device)/127.5-1
                with torch.inference_mode():prediction=model(tensor)[0]
                if not torch.isfinite(prediction).all():raise RetouchError('segmentation','Mask wajah mengandung NaN/Inf.')
                face['labels']=prediction.argmax(1)[0].cpu().numpy().astype(np.uint8)
                del prediction,tensor
            return aligned
        return self.manager.run('parser',parse) if aligned else []
    def createSkinMask(self,labels):
        import numpy as np
        return np.isin(labels,[1]).astype(np.float32)


class FaceRestorer:
    def __init__(self,manager):self.manager=manager
    def restoreFace(self,face,model_name=None,fidelity=.8):
        import numpy as np,torch
        model_name=model_name or self.manager.config['face_restorer']
        key=(model_name,float(fidelity) if model_name=='codeformer' else None)
        if face.get('restored_key')==key:return face['restored']
        def restore(model):
            tensor=torch.from_numpy(np.ascontiguousarray(face['aligned'].transpose(2,0,1))).float().unsqueeze(0).to(self.manager.device)/127.5-1
            with torch.inference_mode():
                if model_name=='codeformer':output=model(tensor,w=fidelity,adain=True)[0]
                else:output=model(tensor,return_rgb=False,randomize_noise=False)[0]
            if not torch.isfinite(output).all():raise RetouchError('inference','Restorasi menghasilkan NaN/Inf.')
            return np.rint((output[0].clamp(-1,1).permute(1,2,0).cpu().numpy()+1)*127.5).clip(0,255).astype(np.uint8)
        face.pop('restored',None);face.pop('restored_key',None)
        face['restored']=self.manager.run('restorer:'+model_name,restore);face['restored_key']=key;return face['restored']
