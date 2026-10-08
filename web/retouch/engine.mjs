// Retouch-only state and geometry. No imports from Upscale and no network calls.
import {ADVANCED_ADJUSTMENTS,applyAdvancedAdjust} from './advanced-adjust.mjs';
import {applyDetailAdjust} from './detail-adjust.mjs';
import {areaHasChanges,neutralAreas} from './area-adjust.mjs';
import {backgroundHasChanges,drawBackground} from './background.mjs';
import {applyHSL,hslHasChanges,adjustHasChanges} from './hsl.mjs';
export const HISTORY_LIMIT = 80;
export const clamp = (value,min,max) => Math.min(max,Math.max(min,value));
export const freshState = () => ({operations:[],adjust:{exposure:0,brightness:0,contrast:0,saturation:0,highlights:0,shadows:0,temperature:0,tint:0,vibrance:0,whites:0,blacks:0,sharpness:0,vignette:0},filter:'none',filterIntensity:100});
// Every operation has a neutral value, so intensity zero leaves Adjust untouched.
export const FILTERS = [
  {id:'none',name:'Original',effects:[]},
  {id:'natural',name:'Natural',effects:[['contrast',1.04],['saturate',1.06]]},
  {id:'vivid',name:'Vivid',effects:[['saturate',1.35],['contrast',1.1]]},
  {id:'warm',name:'Warm',effects:[['sepia',.25],['saturate',1.15]]},
  {id:'cool',name:'Cool',effects:[['hue-rotate',-12],['saturate',.92],['brightness',1.03]]},
  {id:'soft',name:'Soft',effects:[['contrast',.88],['brightness',1.06],['saturate',.9]]},
  {id:'portrait',name:'Portrait',effects:[['sepia',.12],['saturate',.94],['brightness',1.04],['contrast',.96]]},
  {id:'vintage',name:'Vintage',effects:[['sepia',.3],['saturate',.72],['contrast',.85],['brightness',1.08]]},
  {id:'sepia',name:'Sepia',effects:[['sepia',.85]]},
  {id:'mono',name:'Mono',effects:[['grayscale',1]]},
  {id:'dramatic',name:'Dramatic',effects:[['contrast',1.32],['saturate',.7],['brightness',.95]]},
  {id:'matte',name:'Matte',effects:[['contrast',.78],['brightness',1.12],['saturate',.9]]},
  {id:'cinematic',name:'Cinematic',effects:[['contrast',1.18],['saturate',.82],['hue-rotate',-6]]},
  {id:'forest',name:'Forest',effects:[['saturate',1.18],['hue-rotate',8],['contrast',1.06]]},
  {id:'fade',name:'Fade',effects:[['contrast',.72],['saturate',.82],['brightness',1.08]]},
  {id:'noir',name:'Noir',effects:[['grayscale',1],['contrast',1.35],['brightness',.95]]},
  {id:'golden-hour',name:'Golden Hour',effects:[['sepia',.32],['saturate',1.28],['brightness',1.08],['contrast',1.06]]},
  {id:'amber',name:'Amber',effects:[['sepia',.55],['saturate',1.4],['contrast',1.12],['brightness',.98]]},
  {id:'peach',name:'Peach',effects:[['sepia',.18],['hue-rotate',-18],['saturate',.85],['brightness',1.12],['contrast',.92]]},
  {id:'rose',name:'Rose',effects:[['sepia',.24],['hue-rotate',-35],['saturate',1.12],['brightness',1.05]]},
  {id:'lavender',name:'Lavender',effects:[['sepia',.18],['hue-rotate',-70],['saturate',.78],['brightness',1.1],['contrast',.9]]},
  {id:'arctic',name:'Arctic',effects:[['sepia',.22],['hue-rotate',165],['saturate',.72],['brightness',1.08],['contrast',1.12]]},
  {id:'ocean',name:'Ocean',effects:[['sepia',.28],['hue-rotate',145],['saturate',1.18],['contrast',1.15],['brightness',.96]]},
  {id:'emerald',name:'Emerald',effects:[['sepia',.2],['hue-rotate',65],['saturate',1.22],['contrast',1.12]]},
  {id:'pastel',name:'Pastel',effects:[['saturate',.6],['contrast',.8],['brightness',1.16]]},
  {id:'airy',name:'Airy',effects:[['saturate',.88],['contrast',.9],['brightness',1.2]]},
  {id:'moody',name:'Moody',effects:[['saturate',.65],['contrast',1.22],['brightness',.84]]},
  {id:'chrome',name:'Chrome',effects:[['saturate',1.45],['contrast',1.22],['brightness',1.02]]},
  {id:'retro-film',name:'Retro Film',effects:[['sepia',.4],['saturate',.58],['contrast',.92],['brightness',1.03]]},
  {id:'silver',name:'Silver',effects:[['grayscale',1],['contrast',1.08],['brightness',1.12]]},
  {id:'charcoal',name:'Charcoal',effects:[['grayscale',1],['contrast',1.55],['brightness',.82]]},
  {id:'warm-mono',name:'Warm Mono',effects:[['grayscale',1],['sepia',.24],['contrast',1.12],['brightness',1.04]]}
];
export const clone = state => JSON.parse(JSON.stringify(state));
export const signature = state => JSON.stringify(state);
export function cancelPendingLook(state,tool){
  const next=clone(state);
  if(tool==='adjust'){next.adjust=freshState().adjust;neutralAreas(next)}
  else if(tool==='background'){delete next.background}
  else if(tool==='filter'){next.filter='none';next.filterIntensity=100}
  else return null;
  return signature(next)===signature(state)?null:next;
}
export function stackFilter(state){
  if(state.filter==='none'||!FILTERS.some(f=>f.id===state.filter)||(state.filterIntensity??100)<=0)return null;
  return stackLook(state);
}
export function stackAdjust(state){
  if(!adjustHasChanges(state.adjust)&&!areaHasChanges(state.area))return null;
  return stackLook(state);
}
export function stackBackground(state){return backgroundHasChanges(state.background)?stackLook(state):null}
function stackLook(state){
  const next=clone(state);
  // Store a recipe, not a bitmap. Baking Adjust too preserves the exact current look.
  next.operations.push({type:'look',adjust:clone(state.adjust),filter:state.filter,filterIntensity:state.filterIntensity??100});
  if(areaHasChanges(state.area))next.operations.at(-1).area=clone(state.area);
  if(backgroundHasChanges(state.background))next.operations.at(-1).background=clone(state.background);
  delete next.background;
  neutralAreas(next);
  next.adjust=freshState().adjust;next.filter='none';next.filterIntensity=100;
  return next;
}

export class EditHistory {
  constructor(limit=HISTORY_LIMIT){this.limit=limit;this.reset()}
  reset(){this.entries=[freshState()];this.index=0}
  get current(){return clone(this.entries[this.index])}
  get canUndo(){return this.index>0}
  get canRedo(){return this.index<this.entries.length-1}
  push(state){
    if(signature(state)===signature(this.entries[this.index]))return false;
    this.entries.splice(this.index+1);this.entries.push(clone(state));
    if(this.entries.length>this.limit)this.entries.shift();
    this.index=this.entries.length-1;return true;
  }
  undo(){if(this.canUndo)this.index--;return this.current}
  redo(){if(this.canRedo)this.index++;return this.current}
}

export function fitZoom(width,height,viewWidth,viewHeight){
  return Math.min(1,Math.max(.001,Math.min(Math.max(1,viewWidth-64)/width,Math.max(1,viewHeight-64)/height)));
}
export function centeredCrop(width,height,ratio=0){
  let w=width*.8,h=height*.8;
  if(ratio>0){if(w/h>ratio)w=h*ratio;else h=w/ratio}
  return {x:(width-w)/2,y:(height-h)/2,w,h};
}
export function moveCrop(rect,dx,dy,width,height){
  return {...rect,x:clamp(rect.x+dx,0,width-rect.w),y:clamp(rect.y+dy,0,height-rect.h)};
}
export function resizeCrop(rect,handle,dx,dy,width,height,ratio=0){
  const left=handle.includes('w'),right=handle.includes('e'),top=handle.includes('n'),bottom=handle.includes('s');
  const min=Math.min(8,width,height);
  if(!ratio){
    let x1=rect.x,y1=rect.y,x2=rect.x+rect.w,y2=rect.y+rect.h;
    if(left)x1=clamp(x1+dx,0,x2-min);if(right)x2=clamp(x2+dx,x1+min,width);
    if(top)y1=clamp(y1+dy,0,y2-min);if(bottom)y2=clamp(y2+dy,y1+min,height);
    return {x:x1,y:y1,w:x2-x1,h:y2-y1};
  }
  // Keep the opposite corner (or edge centre) fixed while preserving ratio.
  const anchorX=left?rect.x+rect.w:right?rect.x:rect.x+rect.w/2;
  const anchorY=top?rect.y+rect.h:bottom?rect.y:rect.y+rect.h/2;
  let w=left?rect.w-dx:right?rect.w+dx:(top?rect.h-dy:rect.h+dy)*ratio;
  if((top||bottom)&&(left||right)&&Math.abs(dy*ratio)>Math.abs(dx))w=(top?rect.h-dy:rect.h+dy)*ratio;
  const maxW=left?anchorX:right?width-anchorX:2*Math.min(anchorX,width-anchorX);
  const maxH=top?anchorY:bottom?height-anchorY:2*Math.min(anchorY,height-anchorY);
  w=clamp(w,Math.min(min, maxW,maxH*ratio),Math.min(maxW,maxH*ratio));
  const h=w/ratio;
  return {x:left?anchorX-w:right?anchorX:anchorX-w/2,y:top?anchorY-h:bottom?anchorY:anchorY-h/2,w,h};
}
export function integerCrop(rect,width,height){
  const x=clamp(Math.round(rect.x),0,width-1),y=clamp(Math.round(rect.y),0,height-1);
  return {x,y,w:clamp(Math.round(rect.w),1,width-x),h:clamp(Math.round(rect.h),1,height-y)};
}
export function exportSize(width,height,originalWidth,originalHeight,mode){
  if(mode!=='original')return {width,height};
  const scale=Math.max(originalWidth,originalHeight)/Math.max(width,height);
  return {width:Math.max(1,Math.round(width*scale)),height:Math.max(1,Math.round(height*scale))};
}
export function filterString(state){
  const a=state.adjust;
  const filters=[`brightness(${2**a.exposure*(1+a.brightness/100)})`,`contrast(${1+a.contrast/100})`,`saturate(${1+a.saturation/100})`];
  const preset=presetFilterString(state);if(preset)filters.push(preset);
  return filters.join(' ');
}
function presetFilterString(state){
  const filters=[];
  const intensity=clamp(Number.isFinite(state.filterIntensity)?state.filterIntensity:100,0,100)/100;
  if(intensity>0)for(const [name,value] of FILTERS.find(f=>f.id===state.filter)?.effects||[]){
    const neutral=['sepia','grayscale','hue-rotate'].includes(name)?0:1;
    const amount=Number((neutral+(value-neutral)*intensity).toFixed(5));
    filters.push(`${name}(${amount}${name==='hue-rotate'?'deg':''})`);
  }
  return filters.join(' ');
}
function canvas(width,height){const c=document.createElement('canvas');c.width=width;c.height=height;return c}
// Geometry is always replayed from the untouched original, never from previous pixels.
export function renderGeometry(original,operations,snapshot=()=>null,mask=()=>null){
  let start=0,source=original;
  for(let index=operations.length-1;index>=0;index--){
    if(operations[index].type==='retouch'){
      source=snapshot(operations[index].id);
      if(!source)throw new Error('Snapshot AI Retouch belum dimuat.');
      start=index+1;break;
    }
  }
  let current=canvas(source.naturalWidth,source.naturalHeight);
  current.getContext('2d').drawImage(source,0,0);
  for(const [offset,op] of operations.slice(start).entries()){
    const w=current.width,h=current.height;
    let next,ctx;
    if(op.type==='resize'){
      if(!Number.isInteger(op.width)||!Number.isInteger(op.height)||op.width<1||op.height<1||op.width>w||op.height>h)throw new Error('Ukuran pengurangan resolusi tidak valid.');
      next=canvas(op.width,op.height);ctx=next.getContext('2d');ctx.imageSmoothingEnabled=true;ctx.imageSmoothingQuality='high';
      ctx.drawImage(current,0,0,w,h,0,0,op.width,op.height);
    }else if(op.type==='crop'){
      const r=integerCrop(op,w,h);next=canvas(r.w,r.h);next.getContext('2d').drawImage(current,r.x,r.y,r.w,r.h,0,0,r.w,r.h);
    }else if(op.type==='rotate'){
      next=canvas(h,w);ctx=next.getContext('2d');
      if(op.direction===1){ctx.translate(h,0);ctx.rotate(Math.PI/2)}else{ctx.translate(0,w);ctx.rotate(-Math.PI/2)}
      ctx.drawImage(current,0,0);
    }else if(op.type==='flip'){
      next=canvas(w,h);ctx=next.getContext('2d');ctx.translate(op.axis==='x'?w:0,op.axis==='y'?h:0);ctx.scale(op.axis==='x'?-1:1,op.axis==='y'?-1:1);ctx.drawImage(current,0,0);
    }else if(op.type==='look'){
      next=canvas(w,h);drawPreview(current,op,next,id=>mask(id,operations.slice(0,start+offset)));
    }else throw new Error('Operasi edit tidak dikenali.');
    current.width=0;current.height=0;current=next;
  }
  return current;
}
export function drawPreview(source,state,target,mask=()=>null){
  target.width=source.width;target.height=source.height;
  const ctx=target.getContext('2d');
  if(!('filter' in ctx))throw new Error('Browser ini belum mendukung adjustment canvas. Gunakan browser Chromium terbaru.');
  const advanced=[...ADVANCED_ADJUSTMENTS,'sharpness','vignette'].some(key=>Number.isFinite(state.adjust[key])&&state.adjust[key]!==0);
  const selective=hslHasChanges(state.adjust.hsl),pixelsNeeded=advanced||selective;
  ctx.filter=filterString(pixelsNeeded?{...state,filter:'none'}:state);ctx.drawImage(source,0,0);ctx.filter='none';
  if(pixelsNeeded){
    const image=ctx.getImageData(0,0,target.width,target.height);if(advanced){applyAdvancedAdjust(image.data,state.adjust);applyDetailAdjust(image.data,target.width,target.height,state.adjust)}applyHSL(image.data,state.adjust.hsl);ctx.putImageData(image,0,0);
    const preset=presetFilterString(state);
    if(preset){ctx.filter=preset;ctx.globalCompositeOperation='copy';ctx.drawImage(target,0,0);ctx.globalCompositeOperation='source-over';ctx.filter='none'}
  }
  if(areaHasChanges(state.area)){
    const selection=mask(state.area.mask);if(!selection)throw Error('Mask penyesuaian area tidak tersedia.');
    const base=canvas(target.width,target.height);base.getContext('2d').drawImage(target,0,0);
    ctx.clearRect(0,0,target.width,target.height);
    for(const key of ['person','background']){
      const layer=canvas(target.width,target.height);
      drawPreview(base,{adjust:{...freshState().adjust,...state.area[key]},filter:'none'},layer);
      const lc=layer.getContext('2d');lc.globalCompositeOperation=key==='person'?'destination-in':'destination-out';
      lc.drawImage(selection,0,0,layer.width,layer.height);
      ctx.globalCompositeOperation='lighter';ctx.drawImage(layer,0,0);layer.width=0;layer.height=0;
    }
    ctx.globalCompositeOperation='source-over';base.width=0;base.height=0;
  }
  if(backgroundHasChanges(state.background)){const selection=mask(state.background.mask);if(!selection)throw Error('Mask latar belum tersedia.');drawBackground(target,state.background,selection)}
}
export async function encodeExport(source,type,quality,size){
  if(!['image/jpeg','image/png','image/webp'].includes(type))throw new Error('Format export tidak dikenal.');
  if(size.width*size.height>50_000_000)throw new Error('Ukuran export melebihi batas 50 MP. Pilih Current atau perkecil ukuran.');
  const output=canvas(size.width,size.height),ctx=output.getContext('2d');
  if(type==='image/jpeg'){ctx.fillStyle='#fff';ctx.fillRect(0,0,size.width,size.height)}
  ctx.imageSmoothingEnabled=true;ctx.imageSmoothingQuality='high';
  ctx.drawImage(source,0,0,size.width,size.height);
  const blob=await new Promise(resolve=>output.toBlob(resolve,type,quality));
  output.width=0;output.height=0;
  if(!blob||blob.type!==type)throw new Error('Format export tidak didukung browser ini.');
  return blob;
}
