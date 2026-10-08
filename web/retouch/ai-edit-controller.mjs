import {RetouchService} from './ai-service.mjs';
const $=id=>document.getElementById(id);
export const MASK_POINT_LIMIT=20_000;
export class AIEditController{
  constructor(hooks){
    this.hooks=hooks;this.service=new RetouchService('/api/ai-edit/');this.document=null;this.revision=null;this.sourceSignature=null;
    this.visible=false;this.busy=false;this.job=null;this.serial=0;this.strokes=[];this.paintCount=0;this.eraseCount=0;this.maskVisible=true;this.maskDrawn=0;this.maskStrokes=null;this.drawing=false;this.lastPoint=null;this.temporary=false;this.brush=true;this.eraser=false;
    this.resolutions={lama:512,sd15:512};this.failedKind=null;this.failedResolution=null;
    $('edit-method').onchange=()=>{$('edit-resolution').value=String(this.resolutions[$('edit-method').value]);this.discardPreview();this.sync()};
    $('edit-resolution').onchange=()=>{this.resolutions[$('edit-method').value]=Number($('edit-resolution').value);this.discardPreview();this.sync()};
    $('edit-retry-resolution').onclick=()=>{
      if(this.busy||!this.failedKind)return;
      const kind=this.failedKind,lower=this.failedResolution===1024?768:512;
      $('edit-resolution').value=String(lower);this.resolutions[$('edit-method').value]=lower;this.discardPreview();this.sync();return this.run(kind);
    };
    $('edit-brush').onclick=()=>{this.brush=true;this.eraser=false;this.sync()};
    $('edit-eraser').onclick=()=>{this.brush=true;this.eraser=true;this.sync()};
    $('edit-pan').onclick=()=>{this.brush=false;this.sync()};
    $('edit-clear-mask').onclick=()=>{this.clearMarks();this.discardPreview();this.drawMask()};
    $('edit-show-mask').onclick=()=>{this.maskVisible=!this.maskVisible;this.sync()};
    $('edit-brush-size').oninput=()=>{$('edit-brush-size-value').textContent=$('edit-brush-size').value+' px'};
    for(const id of ['edit-prompt','edit-context','edit-steps','edit-strength','edit-seed','edit-low-memory'])$(id).oninput=()=>{this.discardPreview();this.sync()};
    $('edit-preview').onclick=()=>this.run('preview');
    window.addEventListener('pagehide',()=>{if(this.document&&this.service.token)fetch('/api/ai-edit/release',{method:'POST',keepalive:true,headers:{'X-Studio-Token':this.service.token,'Content-Type':'application/json'},body:JSON.stringify({document:this.document})}).catch(()=>{})});
    this.sync();
  }
  settings(){return {model:$('edit-method').value,resolution:Number($('edit-resolution').value)||512,prompt:$('edit-prompt').value,context:Number($('edit-context').value),steps:Number($('edit-steps').value),strength:Number($('edit-strength').value)/100,seed:Number($('edit-seed').value),low_memory:$('edit-low-memory').checked,strokes:this.strokes.map(s=>({...s}))}}
  canRun(){return this.hooks.hasImage()&&this.strokes.some(s=>!s.erase)&&($('edit-method').value!=='sd15'||!!$('edit-prompt').value.trim())}
  sync(){
    const sd=$('edit-method').value==='sd15';$('edit-prompt-field').hidden=!sd;$('edit-sd-settings').hidden=!sd;
    const resolution=Number($('edit-resolution').value)||512;
    $('edit-model-label').textContent=(sd?'SD 1.5':'LaMa')+' · Lokal · area kerja maksimal '+resolution+' px';
    $('edit-resolution-1024').textContent=sd?'1024 px (eksperimen)':'1024 px';
    $('edit-retry-resolution').hidden=!this.failedKind||this.failedResolution<=512;
    $('edit-retry-resolution').disabled=this.busy||!this.canRun();
    $('edit-retry-resolution').textContent='Coba '+(this.failedResolution===1024?768:512)+' px';
    $('edit-description').textContent=sd?'Tandai area, lalu jelaskan penggantinya. Instruksi bahasa Inggris disarankan.':'Tandai objek yang ingin dihapus. Latar akan diisi dari konteks foto.';
    $('edit-fields').disabled=!this.hooks.hasImage()||this.busy;
    $('edit-preview').disabled=!this.canRun()||this.busy;
    for(const [id,selected] of [['edit-brush',this.brush&&!this.eraser],['edit-eraser',this.brush&&this.eraser],['edit-pan',!this.brush]]){$(id).classList.toggle('selected',selected);$(id).setAttribute('aria-pressed',String(selected))}
    $('edit-progress').hidden=!this.busy;
    $('edit-show-mask').setAttribute('aria-pressed',String(this.maskVisible));$('edit-show-mask').classList.toggle('selected',this.maskVisible);
    $('edit-show-mask').title=this.maskVisible?'Sembunyikan penandaan':'Tampilkan penandaan';$('edit-show-mask').setAttribute('aria-label',$('edit-show-mask').title);
    $('edit-mask-overlay').hidden=!this.visible||!this.maskVisible||!this.strokes.length;
    $('viewport').classList.toggle('edit-brushing',this.visible&&this.brush);
    this.hooks.refresh();
  }
  show(value){this.visible=value;if(!value)this.cancel();this.sync();this.drawMask()}
  discardPreview(){this.failedKind=null;this.failedResolution=null;this.previewImage=null;if(this.temporary){this.temporary=false;this.hooks.restore()}}
  clearMarks(){this.strokes=[];this.paintCount=0;this.eraseCount=0;this.limitNotice=null}
  invalidate(){this.serial++;this.clearMarks();this.lastPoint=null;this.drawing=false;this.discardPreview();this.drawMask();this.sync()}
  async resetDocument(){this.cancel();const old=this.document;this.document=null;this.sourceSignature=null;this.clearMarks();this.drawMask();if(old)await this.service.release(old).catch(()=>{})}
  cancel(){this.serial++;if(this.busy)this.hooks.notice('Pembatalan diminta. Menunggu proses AI berhenti…');if(this.job)this.service.cancel(this.job).catch(e=>this.hooks.notice(e.message,true));this.discardPreview();this.clearMarks();this.drawing=false;this.lastPoint=null;this.drawMask();this.sync()}
  async apply(){return this.run('apply')}
  async run(kind){
    if(this.busy||!this.canRun())return;
    const settings=this.settings();this.hooks.flush();const serial=++this.serial;
    this.failedKind=null;this.failedResolution=null;
    this.busy=true;this.hooks.lock(true);this.sync();
    $('edit-progress-bar').removeAttribute('value');$('edit-progress-text').textContent='Menyiapkan foto dan model…';
    try{
      const source=await this.hooks.source(),signature=this.hooks.signature();
      if(serial!==this.serial)return;
      if(signature!==this.sourceSignature){const upload=await this.service.upload(source,this.document);this.document=upload.document;this.revision=upload.revision;this.sourceSignature=signature}
      if(serial!==this.serial)return;
      const result=await this.service.run(kind,{document:this.document,revision:this.revision,settings},state=>{
        $('edit-progress-text').textContent=state.stage+' · '+state.progress+'%';
        if(state.progress<=10)$('edit-progress-bar').removeAttribute('value');else $('edit-progress-bar').value=state.progress;
      },job=>{this.job=job;if(serial!==this.serial)this.service.cancel(job).catch(()=>{})});
      if(serial!==this.serial)return;
      const image=new Image();image.src=result.url;await image.decode();if(serial!==this.serial)return;
      if(kind==='apply'){this.temporary=false;this.previewImage=null;await this.hooks.apply(result,settings,image);this.clearMarks();this.drawMask();this.hooks.notice('AI Edit diterapkan. Undo untuk kembali ke hasil sebelumnya.')}
      else{this.temporary=true;this.previewImage=image;this.hooks.preview(image);this.hooks.notice('Preview siap. Apply untuk menetapkan, Cancel untuk membatalkan.')}
    }catch(e){if(serial===this.serial){
      if(e.code==='memory'&&settings.resolution>512){this.failedKind=kind;this.failedResolution=settings.resolution}
      this.hooks.notice('AI Edit: '+e.message,true);
    }}
    finally{this.job=null;this.busy=false;this.hooks.lock(false);this.sync()}
  }
  stamp(point){
    // Erasing has its own reserve, so a full paint budget never blocks correction.
    const count=this.eraser?this.eraseCount:this.paintCount,key=this.eraser?'erase':'paint';
    if(count>=MASK_POINT_LIMIT){if(this.limitNotice!==key){this.limitNotice=key;this.hooks.notice(this.eraser?'Batas koreksi tercapai. Jalankan edit ini dahulu atau hapus semua penandaan.':'Batas penandaan tercapai. Penghapus tetap bisa digunakan.',true)}return}
    const size=this.hooks.size(),round=value=>Number(value.toFixed(6));
    const stroke={x:round(Math.min(1,Math.max(0,point.x/size.width))),y:round(Math.min(1,Math.max(0,point.y/size.height))),r:Math.max(.00001,round(Math.min(.5,Number($('edit-brush-size').value)/2/Math.max(size.width,size.height)))),erase:this.eraser};
    const last=this.strokes.at(-1);
    if(last&&last.erase===stroke.erase&&last.r===stroke.r&&Math.hypot(last.x-stroke.x,last.y-stroke.y)<stroke.r*.2)return;
    this.strokes.push(stroke);if(this.eraser)this.eraseCount++;else this.paintCount++;
  }
  pointerDown(e,point){if(!this.visible||!this.brush||this.busy)return false;this.discardPreview();this.drawing=true;this.lastPoint=point;this.stamp(point);this.drawMask();return true}
  pointerMove(point){
    if(!this.drawing)return false;
    const last=this.lastPoint,steps=Math.min(MASK_POINT_LIMIT,Math.ceil(Math.hypot(point.x-last.x,point.y-last.y)/Math.max(1,Number($('edit-brush-size').value)/4)));
    for(let i=1;i<=steps;i++){
      if((this.eraser?this.eraseCount:this.paintCount)>=MASK_POINT_LIMIT){this.stamp(point);break}
      this.stamp({x:last.x+(point.x-last.x)*i/steps,y:last.y+(point.y-last.y)*i/steps});
    }
    this.lastPoint=point;this.drawMask();return true;
  }
  pointerEnd(){this.drawing=false;this.lastPoint=null;this.hooks.refresh()}
  drawMask(){
    const c=$('edit-mask-overlay'),size=this.hooks.size();
    if(c.width!==size.width||c.height!==size.height||this.maskStrokes!==this.strokes||this.maskDrawn>this.strokes.length){c.width=size.width;c.height=size.height;this.maskDrawn=0;this.maskStrokes=this.strokes}
    const ctx=c.getContext('2d');
    // Append only fresh stamps. Avoid replaying 20,000 points on every mouse move.
    for(let i=this.maskDrawn;i<this.strokes.length;i++){const s=this.strokes[i];ctx.globalCompositeOperation=s.erase?'destination-out':'source-over';ctx.fillStyle='#f3ae55';ctx.beginPath();ctx.arc(s.x*size.width,s.y*size.height,s.r*Math.max(size.width,size.height),0,Math.PI*2);ctx.fill()}
    this.maskDrawn=this.strokes.length;
    this.sync();this.hooks.refresh();
  }
}
