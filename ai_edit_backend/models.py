import gc
import importlib.util
from resource_paths import ROOT
from retouch_backend.models import RetouchError

class EditModels:
    timer=None
    def __init__(self):self.device=None;self.role=None;self.cached=None
    def status(self):
        return {'device':self.device or 'auto','loaded':[self.role] if self.cached else [],'available':{
            'lama':(ROOT/'models/ai-edit/big-lama.pt').is_file(),
            'sd15':(ROOT/'models/ai-edit/sd15/model_index.json').is_file() and importlib.util.find_spec('diffusers') is not None}}
    def unload(self):
        self.cached=None;self.role=None;gc.collect()
        import torch
        if torch.cuda.is_available():torch.cuda.empty_cache()
    def infer(self,image,mask,settings,progress):
        import torch
        self.device='cuda' if torch.cuda.is_available() else 'cpu'
        role=settings['model'];path=ROOT/'models/ai-edit'/('big-lama.pt' if role=='lama' else 'sd15')
        if not path.exists():raise RetouchError('missing_model','Bobot AI Edit belum tersedia. Jalankan tools/setup_ai_edit.py dahulu.')
        try:
            if role=='lama':
                model=torch.jit.load(str(path),map_location=self.device).eval();self.cached=model;self.role=role
                import numpy as np
                im=torch.from_numpy(image.copy().transpose(2,0,1)).float().div(255).unsqueeze(0).to(self.device)
                ma=torch.from_numpy((mask>0).astype(np.float32)).unsqueeze(0).unsqueeze(0).to(self.device)
                progress('Menghapus objek',35)
                with torch.inference_mode():output=model(im,ma)[0].permute(1,2,0).cpu().numpy()
                progress('Objek selesai diproses',90)
                return np.rint(output*255).clip(0,255).astype(np.uint8)
            from diffusers import StableDiffusionInpaintPipeline
            from PIL import Image
            import numpy as np
            # Never download while editing. Weights are installed explicitly.
            pipe=StableDiffusionInpaintPipeline.from_pretrained(str(path),torch_dtype=torch.float16 if self.device=='cuda' else torch.float32,variant='fp16',use_safetensors=True,local_files_only=True)
            self.cached=pipe;self.role=role
            pipe.enable_vae_tiling();pipe.enable_attention_slicing('max')
            if self.device=='cuda':
                if settings['low_memory']:pipe.enable_sequential_cpu_offload()
                else:pipe.enable_model_cpu_offload()
            else:pipe.to('cpu')
            progress('Menyiapkan penggantian area',20)
            def callback(p,i,t,kwargs):
                progress('Menghasilkan area baru',20+round(65*(i+1)/max(1,settings['steps'])))
                return kwargs
            with torch.inference_mode():
                result=pipe(prompt=settings['prompt'],image=Image.fromarray(image),mask_image=Image.fromarray(mask),height=image.shape[0],width=image.shape[1],strength=settings['strength'],num_inference_steps=settings['steps'],guidance_scale=7.5,generator=torch.Generator(device='cpu').manual_seed(settings['seed']),callback_on_step_end=callback)
            if result.nsfw_content_detected and any(result.nsfw_content_detected):raise RetouchError('result','Hasil tidak dapat ditampilkan. Ubah instruksi atau penandaan.')
            return np.array(result.images[0].convert('RGB'))
        except torch.cuda.OutOfMemoryError as e:
            raise RetouchError('memory','VRAM tidak cukup. Pilih resolusi pemrosesan lebih rendah dan gunakan mode hemat memori.') from e
        finally:self.unload()
