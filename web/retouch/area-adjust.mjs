import {RetouchService} from './ai-service.mjs';
import {adjustHasChanges} from './hsl.mjs';

export const areaHasChanges=area=>!!area&&['person','background'].some(key=>adjustHasChanges(area[key]));
export function neutralAreas(state){if(state.area)state.area={...state.area,person:{},background:{}}}
export function maskOperations(operations){return operations.filter(op=>['crop','resize','rotate','flip','retouch'].includes(op.type))}
export function projectMask(source,record,operations){
  let width=record.width,height=record.height;
  let current=document.createElement('canvas');current.width=source.width;current.height=source.height;
  current.getContext('2d').drawImage(source,0,0);
  for(const op of operations.slice(record.anchor)){
    if(!['crop','resize','rotate','flip'].includes(op.type))continue;
    const oldWidth=width,oldHeight=height;
    if(op.type==='crop'){width=op.w;height=op.h}
    if(op.type==='resize'){width=op.width;height=op.height}
    if(op.type==='rotate'){width=oldHeight;height=oldWidth}
    const scale=Math.min(1,1024/Math.max(width,height));
    const next=document.createElement('canvas');next.width=Math.max(1,Math.round(width*scale));next.height=Math.max(1,Math.round(height*scale));
    const ctx=next.getContext('2d');ctx.imageSmoothingEnabled=true;
    if(op.type==='crop')ctx.drawImage(current,op.x*current.width/oldWidth,op.y*current.height/oldHeight,op.w*current.width/oldWidth,op.h*current.height/oldHeight,0,0,next.width,next.height);
    else if(op.type==='rotate'){
      if(op.direction===1){ctx.translate(next.width,0);ctx.rotate(Math.PI/2)}else{ctx.translate(0,next.height);ctx.rotate(-Math.PI/2)}
      ctx.drawImage(current,0,0,next.height,next.width);
    }else if(op.type==='flip'){
      ctx.translate(op.axis==='x'?next.width:0,op.axis==='y'?next.height:0);ctx.scale(op.axis==='x'?-1:1,op.axis==='y'?-1:1);
      ctx.drawImage(current,0,0,next.width,next.height);
    }else ctx.drawImage(current,0,0,next.width,next.height);
    current.width=0;current.height=0;current=next;
  }
  return current;
}

export class AreaAdjust {
  constructor(hooks){this.hooks=hooks;this.service=new RetouchService();this.target='all';this.busy=false;this.showMask=false;this.job=null;this.document=null;this.decoded=new Map();this.projected=new Map();this.mode=null;this.stroke=null;this.status='';this.statusTone='';this.serial=0}
  async prepare(state){
    const ids=new Set(state.operations.filter(op=>op.type==='look'&&areaHasChanges(op.area)).map(op=>op.area.mask));
    if(state.area?.mask)ids.add(state.area.mask);
    if(state.background?.mask)ids.add(state.background.mask);
    for(const op of state.operations)if(op.background?.mask)ids.add(op.background.mask);
    for(const id of ids){
      const record=state.areaMasks?.[id];if(!record)throw Error('Area penyesuaian tidak tersedia.');
      if(this.decoded.has(id))continue;
      if(typeof record.png!=='string'||record.png.length>4*1024*1024||!Number.isInteger(record.anchor)||record.anchor<0||record.anchor>state.operations.length||![record.width,record.height].every(n=>Number.isInteger(n)&&n>0)||record.width*record.height>50_000_000)throw Error('Data area tidak valid.');
      const raw=Uint8Array.from(atob(record.png),c=>c.charCodeAt(0));
      const image=await createImageBitmap(new Blob([raw],{type:'image/png'}));
      if(image.width*image.height>1024*1024){image.close();throw Error('Mask area terlalu besar.')}
      const canvas=document.createElement('canvas');canvas.width=image.width;canvas.height=image.height;
      const ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(image,0,0);image.close();
      const pixels=ctx.getImageData(0,0,canvas.width,canvas.height);
      for(let i=0;i<pixels.data.length;i+=4){pixels.data[i+3]=pixels.data[i];pixels.data[i]=pixels.data[i+1]=pixels.data[i+2]=255}
      ctx.putImageData(pixels,0,0);this.decoded.set(id,canvas);
    }
    // Undo may reference older masks; they can be decoded again from the recipe.
    for(const [id,c] of this.decoded)if(!ids.has(id)){c.width=0;c.height=0;this.decoded.delete(id)}
  }
  mask(state,id,operations=state.operations){
    const record=state.areaMasks?.[id],source=this.decoded.get(id);if(!record||!source)throw Error('Area penyesuaian belum dimuat.');
    const key=id+JSON.stringify(maskOperations(operations.slice(record.anchor)));
    if(this.projected.has(key))return this.projected.get(key);
    const projected=projectMask(source,record,operations);this.projected.set(key,projected);
    while(this.projected.size>4){const first=this.projected.keys().next().value;const c=this.projected.get(first);c.width=0;c.height=0;this.projected.delete(first)}
    return projected;
  }
  current(state){if(this.target==='all')return state.adjust;state.area??={person:{},background:{}};return state.area[this.target]??={}}
  async select(target,{force=false}={}){
    if(this.busy)return;
    this.hooks.flush();this.mode=null;
    if(target==='all'){this.target=target;this.hooks.refresh();this.hooks.redraw();return}
    const state=this.hooks.state();
    if(force||!state.area?.mask){
      const serial=++this.serial;this.busy=true;this.statusTone='loading';this.status='Menyiapkan pemisahan area…';this.hooks.lock(true);this.hooks.refresh();
      try{
        const source=await this.hooks.source();
        const upload=await this.service.upload(source);this.document=upload.document;
        const result=await this.service.run('segment',upload,p=>{this.status=p.stage+'…';this.hooks.refresh()},job=>this.job=job);
        if(serial!==this.serial)return;
        if(!result.found){this.target='all';this.statusTone='warning';this.status=result.message;return}
        const id=crypto.randomUUID();
        state.areaMasks??={};state.areaMasks[id]={png:result.mask,width:result.width,height:result.height,anchor:state.operations.length};
        state.area={mask:id,person:force?(state.area?.person||{}):{},background:force?(state.area?.background||{}):{}};await this.prepare(state);this.hooks.commit();this.statusTone='ready';this.status='Area siap. Orang dan latar dapat diatur terpisah.';
      }catch(error){this.target='all';this.statusTone='error';this.status='Pemisahan gagal. '+error.message;return}
      finally{this.job=null;if(this.document)await this.service.release(this.document).catch(()=>{});this.document=null;this.busy=false;this.hooks.lock(false);this.hooks.refresh()}
    }
    this.target=target;this.hooks.refresh();this.hooks.redraw();
  }
  overlay(ctx,state,width,height){
    if(!this.showMask||this.target==='all'||!state.area?.mask)return;
    const mask=this.stroke?.canvas||this.mask(state,state.area.mask);
    const layer=document.createElement('canvas');layer.width=mask.width;layer.height=mask.height;
    const c=layer.getContext('2d');c.fillStyle='#579dde';c.fillRect(0,0,layer.width,layer.height);
    c.globalCompositeOperation=this.target==='person'?'destination-in':'destination-out';c.drawImage(mask,0,0);
    ctx.save();ctx.globalAlpha=.32;ctx.drawImage(layer,0,0,width,height);ctx.restore();layer.width=0;layer.height=0;
  }
  pointerDown(event,point){
    const state=this.hooks.state();if(!this.mode||!state.area?.mask||this.busy)return false;
    this.hooks.flush();const source=this.mask(state,state.area.mask),canvas=document.createElement('canvas');canvas.width=source.width;canvas.height=source.height;canvas.getContext('2d').drawImage(source,0,0);
    this.stroke={canvas};this.paint(point);return true;
  }
  pointerMove(point){if(!this.stroke)return false;this.paint(point);return true}
  paint(point){
    const c=this.stroke.canvas,ctx=c.getContext('2d'),size=this.hooks.size(),scale=c.width/size.width;
    ctx.globalCompositeOperation=this.mode==='person'?'source-over':'destination-out';ctx.fillStyle='#fff';
    const x=point.x*scale,y=point.y*c.height/size.height,radius=Number(document.getElementById('area-brush-size').value)*scale/2;
    if(this.stroke.last){ctx.lineWidth=radius*2;ctx.lineCap='round';ctx.strokeStyle='#fff';ctx.beginPath();ctx.moveTo(this.stroke.last.x,this.stroke.last.y);ctx.lineTo(x,y);ctx.stroke()}
    ctx.beginPath();ctx.arc(x,y,radius,0,Math.PI*2);ctx.fill();this.stroke.last={x,y};this.hooks.redraw();
  }
  pointerUp(){
    if(!this.stroke)return;
    const state=this.hooks.state(),mask=this.stroke.canvas;this.stroke=null;
    const copy=document.createElement('canvas');copy.width=mask.width;copy.height=mask.height;
    const ctx=copy.getContext('2d');ctx.drawImage(mask,0,0);const pixels=ctx.getImageData(0,0,copy.width,copy.height);
    for(let i=0;i<pixels.data.length;i+=4){pixels.data[i]=pixels.data[i+1]=pixels.data[i+2]=pixels.data[i+3];pixels.data[i+3]=255}
    ctx.putImageData(pixels,0,0);const size=this.hooks.size(),id=crypto.randomUUID();
    state.areaMasks[id]={png:copy.toDataURL('image/png').split(',')[1],width:size.width,height:size.height,anchor:state.operations.length};
    state.area={...state.area,mask:id};if(state.background)state.background.mask=id;this.decoded.set(id,mask);copy.width=0;copy.height=0;this.hooks.commit();this.hooks.render();
  }
  reset(){this.serial++;this.target='all';this.showMask=false;this.mode=null;this.status='';this.statusTone='';for(const c of this.decoded.values()){c.width=0;c.height=0}for(const c of this.projected.values()){c.width=0;c.height=0}this.decoded.clear();this.projected.clear()}
}
