"""Offline person segmentation for local Adjust; independent of face restoration."""
import base64
import io
import numpy as np
from PIL import Image
from .models import RetouchError


def person_mask(rgba,manager,progress):
    import cv2
    import torch
    h,w=rgba.shape[:2]
    scale=min(1,768/max(h,w))
    width,height=max(1,round(w*scale)),max(1,round(h*scale))
    rgb=cv2.resize(rgba[:,:,:3],(width,height),interpolation=cv2.INTER_AREA)
    alpha=cv2.resize(rgba[:,:,3],(width,height),interpolation=cv2.INTER_LINEAR)
    progress('Memisahkan orang dan latar',30)
    def infer(model):
        tensor=torch.from_numpy(np.ascontiguousarray(rgb.transpose(2,0,1))).float().unsqueeze(0).to(manager.device)/255
        mean=tensor.new_tensor([.485,.456,.406])[None,:,None,None]
        std=tensor.new_tensor([.229,.224,.225])[None,:,None,None]
        with torch.inference_mode():output=model((tensor-mean)/std)['out']
        if not torch.isfinite(output).all():raise RetouchError('segmentation','Pemisahan area menghasilkan nilai tidak valid.')
        labels=output.argmax(1)[0].cpu().numpy()
        probability=output.softmax(1)[0,15].cpu().numpy()
        return labels,probability
    labels,probability=manager.run('person',infer)
    visible=(alpha>0)
    selected=(labels==15)&visible
    if int(selected.sum())<max(16,int(visible.sum()*.001)):
        return {'found':False,'message':'Orang tidak ditemukan. Gunakan Adjust Semua.'}
    # Retain confident interiors, feather only around detected boundaries.
    hard=selected.astype(np.float32)
    soft=cv2.GaussianBlur(hard,(0,0),1.25)
    boundary=(soft>.001)&(soft<.999)
    soft[boundary]=soft[boundary]*.65+probability[boundary]*.35
    soft[~visible]=0
    mask=np.rint(np.clip(soft,0,1)*255).astype(np.uint8)
    progress('Menyiapkan area penyesuaian',90)
    buffer=io.BytesIO();Image.fromarray(mask).save(buffer,format='PNG')
    return {'found':True,'mask':base64.b64encode(buffer.getvalue()).decode('ascii'),
            'width':w,'height':h,'maskWidth':width,'maskHeight':height}
