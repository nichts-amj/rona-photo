import math
import cv2
import numpy as np
from PIL import Image
MASK_POINT_LIMIT=20_000

def validate(raw):
    if not isinstance(raw,dict):raise ValueError('Pengaturan tidak valid.')
    model=raw.get('model','lama')
    if model not in ('lama','sd15'):raise ValueError('Metode AI Edit tidak dikenal.')
    prompt=raw.get('prompt','')
    if not isinstance(prompt,str) or len(prompt)>1000:raise ValueError('Instruksi maksimal 1000 karakter.')
    if model=='sd15' and not prompt.strip():raise ValueError('Isi instruksi penggantian terlebih dahulu.')
    resolution=raw.get('resolution',512)
    if isinstance(resolution,bool) or not isinstance(resolution,(int,float)) or resolution not in (512,768,1024):raise ValueError('Resolusi pemrosesan harus 512, 768, atau 1024 piksel.')
    out={'model':model,'prompt':prompt.strip(),'resolution':int(resolution)}
    for key,default,low,high in [('context',64,16,256),('steps',20,10,40),('strength',.95,.2,1),('seed',0,0,2147483647)]:
        value=raw.get(key,default)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high:raise ValueError('Nilai '+key+' tidak valid.')
        if key!='strength' and value!=int(value):raise ValueError(key+' harus bilangan bulat.')
        out[key]=value if key=='strength' else int(value)
    out['low_memory']=raw.get('low_memory',True)
    if not isinstance(out['low_memory'],bool):raise ValueError('Mode memori tidak valid.')
    strokes=raw.get('strokes',[])
    if not isinstance(strokes,list) or not 1<=len(strokes)<=MASK_POINT_LIMIT*2:raise ValueError('Tandai area terlebih dahulu (maksimal 20.000 titik brush dan 20.000 titik koreksi).')
    out['strokes']=[]
    for stroke in strokes:
        if not isinstance(stroke,dict):raise ValueError('Mask tidak valid.')
        item={}
        for key,lo,hi in [('x',0,1),('y',0,1),('r',.00001,.5)]:
            v=stroke.get(key)
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not lo<=v<=hi:raise ValueError('Koordinat mask tidak valid.')
            item[key]=v
        item['erase']=stroke.get('erase',False)
        if not isinstance(item['erase'],bool):raise ValueError('Mask erase tidak valid.')
        out['strokes'].append(item)
    erase_count=sum(item['erase'] for item in out['strokes'])
    if erase_count>MASK_POINT_LIMIT or len(strokes)-erase_count>MASK_POINT_LIMIT:raise ValueError('Batas 20.000 titik per alat tercapai.')
    return out

def make_mask(shape,strokes):
    h,w=shape[:2];mask=np.zeros((h,w),np.uint8)
    for s in strokes:
        cv2.circle(mask,(min(w-1,round(s['x']*w)),min(h-1,round(s['y']*h))),max(1,round(s['r']*max(w,h))),0 if s['erase'] else 255,-1)
    return mask

def process(rgba,settings,manager,progress):
    mask=make_mask(rgba.shape,settings['strokes']);mask[rgba[:,:,3]==0]=0
    ys,xs=np.where(mask>0)
    if not len(xs):raise ValueError('Area penandaan kosong. Tandai bagian foto yang ingin diedit.')
    h,w=mask.shape;pad=settings['context']
    x0=max(0,int(xs.min())-pad);x1=min(w,int(xs.max())+pad+1)
    y0=max(0,int(ys.min())-pad);y1=min(h,int(ys.max())+pad+1)
    crop=rgba[y0:y1,x0:x1,:3];local=mask[y0:y1,x0:x1]
    # Keep aspect ratio. Only this bounded work area reaches the model.
    scale=settings.get('resolution',512)/max(crop.shape[:2])
    nw=max(8,round(crop.shape[1]*scale));nh=max(8,round(crop.shape[0]*scale))
    image=cv2.resize(crop,(nw,nh),interpolation=cv2.INTER_AREA if scale<1 else cv2.INTER_LINEAR)
    small=cv2.resize(local,(nw,nh),interpolation=cv2.INTER_NEAREST)
    pw=(-nw)%8;ph=(-nh)%8
    image=cv2.copyMakeBorder(image,0,ph,0,pw,cv2.BORDER_REFLECT_101)
    small=cv2.copyMakeBorder(small,0,ph,0,pw,cv2.BORDER_CONSTANT,value=0)
    progress('Memuat model lokal',10)
    generated=manager.infer(image,small,settings,progress)[:nh,:nw]
    generated=cv2.resize(generated,(crop.shape[1],crop.shape[0]),interpolation=cv2.INTER_LANCZOS4)
    # Feather inside mask only: unmarked pixels and all alpha values stay exact.
    blend=np.minimum(cv2.distanceTransform((local>0).astype(np.uint8),cv2.DIST_L2,3)/3,1)[:,:,None]
    output=rgba.copy();output[y0:y1,x0:x1,:3]=np.rint(crop*(1-blend)+generated*blend).clip(0,255).astype(np.uint8)
    progress('Menggabungkan hasil',96)
    return output
