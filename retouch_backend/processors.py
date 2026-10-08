"""Independent automatic facial restoration and protected manual skin processing."""
import cv2
import numpy as np

CLASSES={'skin':[1],'eyes':[4,5,6],'eyebrows':[2,3],'lips':[11,12,13],'hair':[17],'nose':[10]}

def settings_valid(raw):
    if not isinstance(raw,dict):raise ValueError('Settings Retouch harus berupa object.')
    settings={}
    settings['mode']=raw.get('mode','manual')
    settings['model']=raw.get('model','gfpgan')
    if settings['mode'] not in ('automatic','manual') or settings['model'] not in ('codeformer','gfpgan'):raise ValueError('Mode/model Retouch tidak valid.')
    fidelity=raw.get('fidelity',.8)
    if isinstance(fidelity,bool) or not isinstance(fidelity,(int,float)) or not np.isfinite(fidelity) or not 0<=fidelity<=1:raise ValueError('Fidelity tidak valid.')
    settings['fidelity']=float(fidelity)
    for name,default in [('smooth',50),('blemish',0),('restore',50),('strength',100)]:
        value=raw.get(name,default)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not np.isfinite(value) or not 0<=value<=(125 if name in ('smooth','restore') else 100):raise ValueError('Strength tidak valid: '+name)
        settings[name]=float(value)
    for name in ['texture','eyes','hair','identity']:
        if not isinstance(raw.get(name,True),bool):raise ValueError('Opsi preserve tidak valid.')
        settings[name]=raw.get(name,True)
    settings['auto']=raw.get('auto',False)
    if not isinstance(settings['auto'],bool):raise ValueError('Mode blemish tidak valid.')
    strokes=raw.get('strokes',[])
    if not isinstance(strokes,list) or len(strokes)>1000:raise ValueError('Terlalu banyak penandaan noda (maksimal 1000).')
    for stroke in strokes:
        if not isinstance(stroke,dict):raise ValueError('Penandaan tidak valid.')
        for key in ['x','y','r']:
            value=stroke.get(key)
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not np.isfinite(value) or not 0<=value<=1:raise ValueError('Koordinat penandaan tidak valid.')
    settings['strokes']=strokes
    return settings

def masks(labels,settings):
    skin=(labels==1).astype(np.uint8)
    protected=np.isin(labels,[2,3,10,11,12,13]).astype(np.uint8)
    # Landmark-template guard bands remain conservative when parsing misses a feature.
    cv2.circle(protected,(257,314),20,1,-1)
    cv2.ellipse(protected,(257,371),(65,18),0,0,360,1,-1)
    if settings['eyes']:protected|=np.isin(labels,[4,5,6]).astype(np.uint8)
    if settings['eyes']:
        cv2.ellipse(protected,(193,240),(27,17),0,0,360,1,-1)
        cv2.ellipse(protected,(319,240),(27,17),0,0,360,1,-1)
    if settings['hair']:protected|=(labels==17).astype(np.uint8)
    blocked=cv2.dilate(protected,np.ones((7,7),np.uint8))
    allowed=skin*(1-blocked)
    soft=cv2.GaussianBlur(cv2.erode(allowed,np.ones((3,3),np.uint8)).astype(np.float32),(0,0),2)*allowed
    restoration=np.isin(labels,[1,7,8]).astype(np.uint8)
    if not settings['identity']:
        if not settings['eyes']:restoration|=np.isin(labels,[4,5]).astype(np.uint8)
        if not settings['hair']:restoration|=(labels==17).astype(np.uint8)
    restoration*=1-blocked
    restore_soft=cv2.GaussianBlur(cv2.erode(restoration,np.ones((5,5),np.uint8)).astype(np.float32),(0,0),3)*restoration
    return soft,restore_soft,allowed,restoration

class SkinProcessor:
    def smoothSkin(self,rgb,mask,settings):
        amount=min(1,settings['smooth']/100*settings['strength']/100*.85)
        if amount==0:return rgb.copy()
        source=rgb.astype(np.float32)
        if settings['texture']:
            low=cv2.GaussianBlur(source,(0,0),1.4)
            smooth=cv2.bilateralFilter(low,9,16,5)
            candidate=smooth+(source-low)*.7
        else:candidate=cv2.bilateralFilter(source,9,22,5)
        return source+(candidate-source)*(mask*amount)[:,:,None]

class BlemishProcessor:
    def candidates(self,rgb,skin):
        gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY).astype(np.float32)
        baseline=cv2.medianBlur(gray.astype(np.uint8),9).astype(np.float32)
        redness=rgb[:,:,0].astype(np.float32)-rgb[:,:,1].astype(np.float32)
        local_red=cv2.GaussianBlur(redness,(0,0),3)
        candidate=((baseline-gray>12)&(redness-local_red>8)&(skin>.8)).astype(np.uint8)
        count,components,stats,_=cv2.connectedComponentsWithStats(candidate)
        output=np.zeros_like(candidate)
        for index in range(1,count):
            x,y,w,h,area=stats[index]
            if 2<=area<=40 and max(w,h)<=12 and max(w,h)/max(1,min(w,h))<2.2:output[components==index]=1
        return output
    def removeBlemishes(self,rgb,mask,settings,matrix,size):
        if settings['blemish']==0 or settings['strength']==0:return rgb.astype(np.float32)
        raw=np.rint(rgb).clip(0,255).astype(np.uint8)
        selected=self.candidates(raw,mask) if settings['auto'] else np.zeros(mask.shape,np.uint8)
        w,h=size
        scale=float(np.hypot(matrix[0,0],matrix[0,1]))
        for stroke in settings['strokes']:
            point=matrix@np.array([stroke['x']*w,stroke['y']*h,1])
            radius=max(1,round(stroke['r']*max(w,h)*scale))
            cv2.circle(selected,(round(point[0]),round(point[1])),min(radius,80),1,-1)
        selected*=mask>.5
        if not selected.any():return rgb.astype(np.float32)
        processed=cv2.inpaint(raw,selected*255,2,cv2.INPAINT_TELEA).astype(np.float32)
        soft=cv2.GaussianBlur(selected.astype(np.float32),(0,0),.8)*mask
        return rgb+(processed-rgb)*(soft*settings['blemish']/100*settings['strength']/100*.65)[:,:,None]

def process_image(image,faces,settings,restorer,edge=None,progress=lambda *a:None):
    if settings['mode']=='automatic':return automatic_restore(image,faces,settings,restorer,progress)
    if settings['strength']==0 or not any(settings[k] for k in ['smooth','blemish','restore']):return image.copy()
    h,w=image.shape[:2];scale=min(1,edge/max(w,h)) if edge else 1
    target=cv2.resize(image,(max(1,round(w*scale)),max(1,round(h*scale)))) if scale!=1 else image.copy()
    result=target.copy();skin_processor=SkinProcessor();blemish_processor=BlemishProcessor()
    for index,face in enumerate(faces):
        progress('Memproses wajah',15+int(index/max(1,len(faces))*70))
        labels=face['labels'];skin_mask,rest_mask,skin_allowed,rest_allowed=masks(labels,settings)
        aligned=face['aligned'].astype(np.float32)
        processed=skin_processor.smoothSkin(aligned,skin_mask,settings)
        processed=blemish_processor.removeBlemishes(processed,skin_mask,settings,face['matrix'],(w,h))
        if settings['restore']>0:
            restored=restorer.restoreFace(face,settings['model'],settings['fidelity']).astype(np.float32)
            amount=min(1,settings['restore']/100*settings['strength']/100*(.4 if settings['identity'] else .85))
            processed+=(restored-aligned)*(rest_mask*amount)[:,:,None]
        inverse=cv2.invertAffineTransform(face['matrix'])*scale
        corners=cv2.transform(np.array([[[0,0],[512,0],[512,512],[0,512]]],np.float32),inverse)[0]
        x0,y0=np.maximum(np.floor(corners.min(0)).astype(int),0);x1,y1=np.minimum(np.ceil(corners.max(0)).astype(int),[target.shape[1],target.shape[0]])
        if x1<=x0 or y1<=y0:continue
        matrix=inverse.copy();matrix[:,2]-=[x0,y0]
        delta=cv2.warpAffine(processed-aligned,matrix,(x1-x0,y1-y0),flags=cv2.INTER_LINEAR)
        # Hard support is applied AFTER interpolation: protected pixels remain exact.
        allowed=skin_allowed|rest_allowed if settings['restore']>0 else skin_allowed
        support=cv2.warpAffine(allowed,matrix,(x1-x0,y1-y0),flags=cv2.INTER_NEAREST)>0
        region=result[y0:y1,x0:x1,:3].astype(np.float32)
        region+=delta*support[:,:,None]
        result[y0:y1,x0:x1,:3]=np.rint(region).clip(0,255).astype(np.uint8)
    progress('Menyelesaikan hasil',95);return result


def automatic_restore(image,faces,settings,restorer,progress):
    """Restore full facial features at source resolution; preserve background/alpha."""
    result=image.copy()
    amount=settings['strength']/100*(.4 if settings['identity'] else 1)
    if not amount:return result
    for index,face in enumerate(faces):
        progress('Restorasi wajah · '+settings['model'],15+int(index/max(1,len(faces))*70))
        restored=restorer.restoreFace(face,settings['model'],settings['fidelity']).astype(np.float32)
        labels=face['labels']
        support=np.isin(labels,[1,2,3,4,5,6,7,8,9,10,11,12,13,15]).astype(np.uint8)
        if not settings['hair']:support|=(labels==17).astype(np.uint8)
        protected=np.zeros_like(support)
        if settings['eyes']:protected|=np.isin(labels,[4,5,6]).astype(np.uint8)
        if settings['hair']:protected|=(labels==17).astype(np.uint8)
        support*=1-cv2.dilate(protected,np.ones((7,7),np.uint8))
        if settings['texture']:
            # Keep source skin detail while restoring lower-frequency appearance.
            source=face['aligned'].astype(np.float32)
            source_detail=source-cv2.GaussianBlur(source,(0,0),1.4)
            restored_low=cv2.GaussianBlur(restored,(0,0),1.4)
            skin=(labels==1)[:,:,None]
            restored=np.where(skin,restored_low+source_detail*.7,restored)
        mask=cv2.GaussianBlur(support.astype(np.float32),(101,101),11)
        mask=cv2.GaussianBlur(mask,(101,101),11)*support
        mask[:10,:]=0;mask[-10:,:]=0;mask[:,:10]=0;mask[:,-10:]=0
        inverse=cv2.invertAffineTransform(face['matrix'])
        corners=cv2.transform(np.array([[[0,0],[512,0],[512,512],[0,512]]],np.float32),inverse)[0]
        x0,y0=np.maximum(np.floor(corners.min(0)).astype(int),0)
        x1,y1=np.minimum(np.ceil(corners.max(0)).astype(int),[image.shape[1],image.shape[0]])
        if x1<=x0 or y1<=y0:continue
        inverse[:,2]-=[x0,y0]
        size=(x1-x0,y1-y0)
        delta=(restored-face['aligned'].astype(np.float32))*(mask*amount)[:,:,None]
        warped=cv2.warpAffine(delta,inverse,size,flags=cv2.INTER_LINEAR)
        hard=cv2.warpAffine(support,inverse,size,flags=cv2.INTER_NEAREST)>0
        region=result[y0:y1,x0:x1,:3].astype(np.float32)+warped*hard[:,:,None]
        result[y0:y1,x0:x1,:3]=np.rint(region).clip(0,255).astype(np.uint8)
    progress('Menyelesaikan hasil',95)
    return result
