"""Pinned HAT / CodeFormer / GFPGAN adapters; one restoration model on GPU."""
import gc
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from pipeline.io import sha256

from pipeline.performance import NonFiniteOutput, TileProfiler, autocast, precision_for, adaptive_tile, run_with_fallback
from resource_paths import ROOT
WEIGHTS={'H':'Real_HAT_GAN_SRx4.pth','F':'codeformer.pth','G':'GFPGANv1.4.pth'}


def availability():
    available={m:(ROOT/'models'/name).is_file() for m,name in WEIGHTS.items()}
    dependencies=all(importlib.util.find_spec(p) for p in ('basicsr','facexlib','cv2','einops','scipy','numba'))
    for m in available:
        available[m]=bool(available[m] and dependencies and (ROOT/'models/extra-provenance.json').is_file())
    return {'A':(ROOT/'models/provenance.json').exists(),'B':(ROOT/'models/realesrgan-provenance.json').exists(),
            'S':(ROOT/'models/swin2sr-provenance.json').exists(),**available}


def compatibility():
    # BasicSR 1.4.2 imports a torchvision namespace removed in recent versions.
    # The grayscale function it needs is now in functional; no installed file is edited.
    import torchvision.transforms.functional as functional
    sys.modules.setdefault('torchvision.transforms.functional_tensor',functional)
    import basicsr


def load_module(name,path):
    if name in sys.modules:
        return sys.modules[name]
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name,None)
        raise
    return module


def hat_tiles(rgb,model,device,tile=64,progress=None,floating=False,precision=None):
    if tile not in (64,96,128):
        raise ValueError('HAT tile harus 64, 96, atau 128.')
    h,w=rgb.shape[:2]
    # Official HAT reflect pad to window-size multiple; no extra pad if aligned.
    padded=np.pad(rgb,((0,(-h)%16),(0,(-w)%16),(0,0)),mode='reflect')
    ph,pw=padded.shape[:2]
    output=np.empty((ph*4,pw*4,3),dtype=np.float32 if floating else np.uint8)
    total=((ph+tile-1)//tile)*((pw+tile-1)//tile)
    index=0
    profiler=TileProfiler(device)
    with torch.inference_mode(), autocast(device, precision):
        for y in range(0,ph,tile):
            for x in range(0,pw,tile):
                y1,x1=min(y+tile,ph),min(x+tile,pw)
                py,px=max(y-32,0),max(x-32,0)
                py1,px1=min(y1+32,ph),min(x1+32,pw)
                patch=profiler.call("upload_seconds",lambda: torch.from_numpy(np.ascontiguousarray(padded[py:py1,px:px1].transpose(2,0,1))).unsqueeze(0).to(device,torch.float32)/255)
                prediction=profiler.forward(model,patch,precision)
                if prediction.shape!=(1,3,(py1-py)*4,(px1-px)*4):
                    raise RuntimeError('Keluaran HAT tidak valid.')
                core=profiler.download(lambda: prediction[0,:,(y-py)*4:(y1-py)*4,(x-px)*4:(x1-px)*4].permute(1,2,0).float().cpu().numpy())
                merge_start=time.perf_counter()
                if not np.isfinite(core).all():
                    raise NonFiniteOutput("NaN/Inf in HAT output")
                output[y*4:y1*4,x*4:x1*4]=core if floating else np.rint(np.clip(core,0,1)*255).astype(np.uint8)
                profiler.times["cpu_merge_seconds"]+=time.perf_counter()-merge_start
                del patch,prediction,core
                index+=1
                if progress:progress(index,total,tile)
    return output[:h*4,:w*4],{'tiles':total,'tile_used':tile,'context':32,'window_size':16,'timings':profiler.report()}


class ExtraModel:
    def __init__(self,model,device='cuda'):
        if model not in WEIGHTS or device not in ('cuda','cpu'):
            raise ValueError('Model/perangkat tidak valid.')
        if device=='cuda' and not torch.cuda.is_available():
            raise RuntimeError('CUDA tidak tersedia. Pilih CPU secara eksplisit.')
        self.name=model;self.device=torch.device(device);self.model=None;self.helper=None
        self.provenance=json.loads((ROOT/'models/extra-provenance.json').read_text(encoding='utf-8'))
        required=[WEIGHTS[model]]+(['detection_Resnet50_Final.pth','parsing_parsenet.pth'] if model!='H' else [])
        for name in required:
            if sha256(ROOT/'models'/name)!=self.provenance['weights'][name]['sha256']:
                raise RuntimeError('Integritas bobot tidak cocok: '+name)
        source_name={'H':'hat','F':'codeformer','G':'gfpgan'}[model]
        for path,digest in self.provenance['sources'][source_name]['hashes'].items():
            if sha256(ROOT/path)!=digest:
                raise RuntimeError('Integritas kode model tidak cocok: '+path)
        compatibility()
        torch.backends.cuda.matmul.allow_tf32=False
        torch.backends.cudnn.allow_tf32=False
        torch.backends.cudnn.benchmark=False

    def _load_restorer(self):
        if self.name=='H':
            module=load_module('third_party.hat.hat_arch',ROOT/'third_party/hat/hat_arch.py')
            self.model=module.HAT(upscale=4,in_chans=3,img_size=64,window_size=16,compress_ratio=3,
                squeeze_factor=30,conv_scale=.01,overlap_ratio=.5,img_range=1.,depths=[6]*6,
                embed_dim=180,num_heads=[6]*6,mlp_ratio=2,upsampler='pixelshuffle',resi_connection='1conv')
        elif self.name=='F':
            load_module('basicsr.archs.vqgan_arch',ROOT/'third_party/codeformer/vqgan_arch.py')
            module=load_module('third_party.codeformer.codeformer_arch',ROOT/'third_party/codeformer/codeformer_arch.py')
            self.model=module.CodeFormer(dim_embd=512,codebook_size=1024,n_head=8,n_layers=9,connect_list=['32','64','128','256'])
        else:
            # Import the namespace parent so the official relative architecture import works.
            import third_party.gfpgan
            module=load_module('third_party.gfpgan.gfpganv1_clean_arch',ROOT/'third_party/gfpgan/gfpganv1_clean_arch.py')
            self.model=module.GFPGANv1Clean(out_size=512,num_style_feat=512,channel_multiplier=2,
                decoder_load_path=None,fix_decoder=False,num_mlp=8,input_is_latent=True,different_w=True,narrow=1,sft_half=True)
        state=torch.load(ROOT/'models'/WEIGHTS[self.name],map_location='cpu',weights_only=True)
        self.model.load_state_dict(state['params_ema'],strict=True)
        del state
        self.model.eval().to(self.device)

    def infer(self,image,config,progress=None):
        if image.mode!='RGB' or image.width*image.height>50_000_000:
            raise ValueError('Foto RGB maksimal 50 MP diperlukan.')
        scale=config.get('output_scale',2)
        if scale not in (2,4):raise ValueError('Skala keluaran harus 2 atau 4.')
        start=time.perf_counter()
        if self.device.type=='cuda':torch.cuda.reset_peak_memory_stats()
        if self.name=='H':
            load_start=time.perf_counter()
            if self.model is None:
                self._load_restorer()
            if self.device.type=='cuda':torch.cuda.synchronize()
            load_seconds=time.perf_counter()-load_start
            precision=precision_for(self.device,'H',getattr(self,'gpu_optimization',False))
            requested_tile=config['h_tile']
            initial_tile=adaptive_tile(self.device,'H',requested_tile,precision)
            def run(dtype):
                attempts=[]
                for tile in sorted({initial_tile,*(x for x in (96,64) if x<initial_tile)},reverse=True):
                    try:
                        native,info=hat_tiles(np.asarray(image),self.model,self.device,tile,progress,precision=dtype)
                        attempts.append({'tile':tile,'status':'success'})
                        return native,{**info,'attempts':attempts}
                    except torch.cuda.OutOfMemoryError:
                        attempts.append({'tile':tile,'status':'cuda_oom'})
                    gc.collect();torch.cuda.empty_cache()
                raise RuntimeError('Memori GPU HAT tidak cukup, termasuk pada potongan 64.')
            native,info=run_with_fallback(run,self.device,precision)
            info.update(tile_requested=requested_tile,model_load_seconds=load_seconds)
            result=Image.fromarray(native)
            if scale==2:
                result=result.resize((image.width*2,image.height*2),Image.Resampling.LANCZOS)
            info.update(native_scale=4,resize='none (native x4)' if scale==4 else 'Pillow Lanczos RGB8 x4 to x2')
        else:
            result,info=self._faces(image,config,progress)
        if self.device.type=='cuda':torch.cuda.synchronize()
        info.update(model=WEIGHTS[self.name],seconds=time.perf_counter()-start,output_scale=scale,
            device=str(self.device),peak_cuda_reserved_bytes=torch.cuda.max_memory_reserved() if self.device.type=='cuda' else None)
        info.setdefault('precision','float32')
        return result,info

    def _faces(self,image,config,progress):
        import cv2
        from facexlib.utils.face_restoration_helper import FaceRestoreHelper
        # Detector and parser on CPU. Their inference never overlaps GPU restoration.
        if progress:progress(0,1,512)
        self.helper=FaceRestoreHelper(config.get('output_scale',2),face_size=512,det_model='retinaface_resnet50',use_parse=True,
                                      device=torch.device('cpu'),model_rootpath=str(ROOT/'models'))
        helper=self.helper
        helper.read_image(np.asarray(image)[:,:,::-1].copy())
        helper.get_face_landmarks_5(only_center_face=False,resize=640,eye_dist_threshold=5)
        helper.align_warp_face()
        count=len(helper.cropped_faces)
        helper.face_det=None
        gc.collect()
        if count:
            self._load_restorer()
        for i,face in enumerate(helper.cropped_faces):
            if progress:progress(i,max(1,count),512)
            tensor=torch.from_numpy(np.ascontiguousarray(face[:,:,::-1].transpose(2,0,1))).unsqueeze(0).to(self.device,torch.float32)/127.5-1
            with torch.inference_mode():
                if self.name=='F':output=self.model(tensor,w=config['fidelity'],adain=True)[0]
                else:output=self.model(tensor,return_rgb=False,randomize_noise=False)[0]
            if not torch.isfinite(output).all():raise RuntimeError('Keluaran wajah mengandung NaN/Inf.')
            rgb=np.rint((output[0].clamp(-1,1).permute(1,2,0).cpu().numpy()+1)*127.5).astype(np.uint8)
            helper.add_restored_face(rgb[:,:,::-1].copy())
            del output,tensor,rgb
            if progress:progress(i+1,count,512)
        # Release restorer before face parsing and compositing.
        self.model=None;gc.collect()
        if self.device.type=='cuda':torch.cuda.empty_cache()
        helper.get_inverse_affine(None)
        scale=config.get('output_scale',2)
        height,width=image.height*scale,image.width*scale
        foreground=np.zeros((height,width,3),dtype=np.float32)
        transmission=np.ones((height,width,1),dtype=np.float32)
        # Parsing and affine blending adapted from facexlib 0.3.0 FaceRestoreHelper.
        # Premultiplied layers make it possible to reuse faces with any background.
        for i,(face,inverse) in enumerate(zip(helper.restored_faces,helper.inverse_affine_matrices)):
            if progress:progress(i,max(1,count),512)
            matrix=inverse.copy();matrix[:,2]+=(scale/2)
            warped=cv2.warpAffine(face,matrix,(width,height))[:,:,::-1]
            tensor=torch.from_numpy(np.ascontiguousarray(face[:,:,::-1].transpose(2,0,1))).float().unsqueeze(0)/127.5-1
            with torch.inference_mode():labels=helper.face_parse(tensor)[0].argmax(dim=1).squeeze().numpy()
            mask=np.isin(labels,[1,2,3,4,5,6,7,8,9,10,11,12,13,15]).astype(np.float32)
            mask=cv2.GaussianBlur(cv2.GaussianBlur(mask,(101,101),11),(101,101),11)
            mask[:10,:]=0;mask[-10:,:]=0;mask[:,:10]=0;mask[:,-10:]=0
            mask=np.clip(cv2.warpAffine(mask,matrix,(width,height),flags=cv2.INTER_AREA),0,1)[:,:,None]
            foreground=mask*warped+(1-mask)*foreground
            transmission*=1-mask
            del tensor,labels,mask,warped
        base=np.asarray(image.resize((width,height),Image.Resampling.LANCZOS),dtype=np.float32)
        result=Image.fromarray(np.rint(foreground+base*transmission).clip(0,255).astype(np.uint8))
        return result,{'faces_detected':count,'detector_device':'cpu','parser_device':'cpu',
            'face_size':512,'fidelity':config['fidelity'] if self.name=='F' else None,
            'noise':'fixed' if self.name=='G' else None,'background':'Pillow Lanczos, no background restoration',
            'note':'No faces detected; background resize only.' if not count else 'Generative face restoration; inspect identity and facial details.',
            '_face_layer':Image.fromarray(np.rint(foreground).clip(0,255).astype(np.uint8)),
            '_transmission':Image.fromarray(np.repeat(np.rint(transmission*255).clip(0,255).astype(np.uint8),3,axis=2))}

    def close(self):
        self.model=None;self.helper=None;gc.collect()
        if self.device.type=='cuda':torch.cuda.empty_cache()
