import {RetouchService,SnapshotStore} from './ai-service.mjs';
const $=id=>document.getElementById(id);
export class AIRetouchController {
  constructor(hooks){
    this.hooks=hooks;this.service=new RetouchService();this.snapshots=new SnapshotStore();this.document=null;this.revision=null;
    this.analysis=null;this.sourceSignature=null;this.busy=false;this.serial=0;this.job=null;this.timer=null;this.pending=false;this.brush=false;this.drawing=false;this.strokes=[];this.temporary=false;this.previewImage=null;this.previewSettingsKey=null;this.visible=false;
    this.analysisTimer=null;
    this.scanning=false;
    this.pausedAfterSave=false;
    this.repeatApproved=false;
    this.repeatApprovedKey=null;
    this.repeatDismissed=false;
    $('retouch-again-accept').onclick=()=>{
      if(!this.visible||this.busy||!this.hooks.hasImage())return;
      this.repeatApproved=true;this.repeatDismissed=false;
      this.repeatApprovedKey=this.hooks.appliedRetouchKey?.()??null;
      $('retouch-again-notice').hidden=true;
      this.resumeAfterSave();this.show(true);
    };
    $('retouch-again-decline').onclick=()=>{
      this.repeatDismissed=true;$('retouch-again-notice').hidden=true;
      this.faceStatus('idle','Hasil tetap dipertahankan. Klik ikon Retouch jika ingin mengedit lagi.');
      this.sync();
    };
    $('ai-fidelity').oninput=()=>{this.sync();this.schedule()};
    $('ai-model').onchange=()=>{this.sync();this.schedule(0)};
    $('ai-face-zoom').onclick=()=>this.hooks.focusFace?.(this.analysis?.faces[0]?.bbox);
    $('ai-retry').onclick=()=>this.analyze();
    $('ai-apply').onclick=()=>this.apply();$('ai-cancel').onclick=()=>this.cancel();
    for(const key of ['smooth','restore','strength'])$('ai-'+key).oninput=()=>{$('ai-'+key+'-value').textContent=$('ai-'+key).value;this.schedule()};
    for(const key of ['texture','eyes','hair','identity'])$('ai-'+key).onchange=()=>this.schedule();
    $('ai-debug-mask').onchange=()=>this.debugMask();
    window.addEventListener('pagehide',()=>{if(this.document&&this.service.token)fetch('/api/retouch/release',{method:'POST',keepalive:true,headers:{'X-Studio-Token':this.service.token,'Content-Type':'application/json'},body:JSON.stringify({document:this.document})}).catch(()=>{})});
    this.sync();
  }
  settings(){
    const value={strokes:[],blemish:0,auto:false};
    for(const key of ['smooth','restore','strength'])value[key]=Number($('ai-'+key).value);
    for(const key of ['texture','eyes','hair','identity'])value[key]=$('ai-'+key).checked;
    value.mode='manual';value.model=$('ai-model').value||'gfpgan';value.fidelity=Number($('ai-fidelity').value)/100;
    return value;
  }
  sync(){
    $('ai-fidelity-field').hidden=$('ai-model').value==='gfpgan';
    $('ai-fidelity-value').textContent=(Number($('ai-fidelity').value)/100).toFixed(2);
    $('ai-model-description').textContent=$('ai-model').value==='gfpgan'?'Restorasi wajah dengan GFPGAN.':'Restorasi wajah dengan CodeFormer. Kesetiaan lebih tinggi menjaga kemiripan dengan sumber.';
    const ready=!!this.analysis?.faces.length&&!this.pausedAfterSave&&!this.needsRepeatConsent();
    $('ai-controls').disabled=!ready;
    $('ai-apply').disabled=!ready||this.busy;$('ai-cancel').disabled=!this.analysis&&!this.busy&&!this.temporary;
    $('ai-progress').hidden=!this.busy;
    $('ai-retry').disabled=this.busy||this.pausedAfterSave||!this.hooks.hasImage();
    $('viewport').classList.toggle('blemish-brush',this.visible&&this.brush&&ready);
    $('ai-brush-overlay').hidden=!this.visible||!this.strokes.length;
  }
  faceStatus(state,text){
    $('ai-scan-status').dataset.state=state;
    $('ai-face-status').textContent=text;
    $('ai-status-icon').textContent={idle:'▧',scanning:'',ready:'✓',empty:'!',error:'×',cancelled:'i'}[state];
    $('ai-retry').hidden=!['error','cancelled'].includes(state);
  }
  analysisStatus(notify=false){
    const count=this.analysis?.faces.length||0;
    const text=count?`${count} wajah ditemukan. Hasil pemindaian tersimpan sementara.`:'Tidak ada wajah terdeteksi. Coba foto dengan wajah yang lebih jelas.';
    this.faceStatus(count?'ready':'empty',text);
    if(notify)this.hooks.notice(text,false,count?'success':'warning',6000);
  }
  queueAnalysis(){
    clearTimeout(this.analysisTimer);
    if(this.pausedAfterSave||this.needsRepeatConsent())return;
    this.analysisTimer=setTimeout(()=>{
      if(this.visible&&this.hooks.hasImage()&&!this.busy&&!this.analysis)this.analyze();
    },0);
  }
  show(visible){
    this.visible=visible;
    if(!visible){
      $('retouch-again-notice').hidden=true;this.repeatDismissed=false;
      // Navigation preserves the document, analysis, marks and completed preview.
      clearTimeout(this.analysisTimer);clearTimeout(this.timer);this.pending=false;this.serial++;
      if(this.job)this.service.cancel(this.job).catch(()=>{});
      this.brush=false;this.drawing=false;
      $('ai-mask-overlay').hidden=true;this.hooks.restore();
    }else{
      if(this.needsRepeatConsent()){
        if(!this.pausedAfterSave)this.pauseAfterSave();
        $('retouch-again-notice').hidden=this.repeatDismissed||!this.hooks.hasImage();
        this.sync();return;
      }
      $('retouch-again-notice').hidden=true;
      if(this.pausedAfterSave){this.sync();return}
      if(this.analysis&&this.sourceSignature!==this.hooks.signature())this.invalidate();
      if(!this.analysis)this.queueAnalysis();
      else{
        this.analysisStatus();this.debugMask();
        if(this.temporary&&this.previewImage&&this.previewSettingsKey===JSON.stringify(this.settings()))this.hooks.preview(this.previewImage);
        else if(this.analysis.faces.length&&!this.busy)this.schedule(0);
      }
    }
    this.sync();
  }
  photoLoaded(){
    if(this.visible&&this.needsRepeatConsent()){this.show(true);return}
    this.faceStatus('idle','Foto siap. Wajah dipindai otomatis saat menu Retouch aktif.');
    this.queueAnalysis();
  }
  async resetDocument(){
    this.repeatApproved=false;this.repeatApprovedKey=null;this.repeatDismissed=false;$('retouch-again-notice').hidden=true;
    this.pausedAfterSave=false;
    const old=this.document;this.cancel();this.document=null;this.revision=null;this.analysis=null;this.sourceSignature=null;this.strokes=[];this.snapshots.clear();this.sync();
    this.faceStatus('idle','Masukkan foto untuk memindai wajah.');
    if(old)await this.service.release(old).catch(()=>{});
  }
  invalidate(){
    this.cancel();this.analysis=null;this.sourceSignature=null;this.strokes=[];
    this.faceStatus('idle',this.pausedAfterSave?'Klik ikon Retouch untuk memulai langkah baru.':'Foto berubah. Wajah akan dipindai ulang saat Retouch aktif.');$('ai-mask-overlay').hidden=true;this.sync();this.queueAnalysis();
  }
  pauseAfterSave(){
    this.pausedAfterSave=true;clearTimeout(this.analysisTimer);clearTimeout(this.timer);this.pending=false;this.serial++;
    this.faceStatus('idle','Klik ikon Retouch untuk memulai langkah baru.');this.sync();
  }
  needsRepeatConsent(){return !!this.hooks.hasAppliedRetouch?.()&&(!this.repeatApproved||this.repeatApprovedKey!==(this.hooks.appliedRetouchKey?.()??null))}
  resumeAfterSave(){
    if(this.needsRepeatConsent()){
      this.repeatDismissed=false;
      if(!this.pausedAfterSave)this.pauseAfterSave();
      return;
    }
    if(!this.pausedAfterSave)return;
    this.pausedAfterSave=false;this.suppressNextAutoPreview=false;this.sync();
  }
  async task(kind,settings){
    $('ai-progress-bar').value=0;$('ai-progress-text').textContent=(kind==='analyze'?'Memindai wajah':kind==='apply'?'Menerapkan Retouch':'Memperbarui pratinjau')+' · 0%';this.busy=true;this.hooks.lock(true);this.sync();
    try{return await this.service.run(kind,{document:this.document,revision:this.revision,settings},state=>{
      $('ai-progress-bar').value=state.progress;$('ai-progress-text').textContent=state.stage+' · '+state.progress+'%';
    },id=>this.job=id)}
    finally{this.job=null;this.busy=false;this.hooks.lock(false);this.sync();if(this.pending&&kind==='preview'){this.pending=false;this.schedule(0)}}
  }
  async analyze(){
    if(this.pausedAfterSave||this.needsRepeatConsent()||this.busy||!this.visible||!this.hooks.hasImage())return;this.cancel();this.hooks.flush();this.busy=true;this.hooks.lock(true);this.sync();const serial=this.serial;
    this.scanning=true;this.faceStatus('scanning','Sedang memindai wajah…');
    $('ai-progress-bar').value=0;$('ai-progress-text').textContent='Menyiapkan pemindaian…';
    try{
      const source=await this.hooks.source();const current=this.hooks.signature();
      const status=await this.service.status();$('ai-debug').hidden=!status.debug;
      if(serial!==this.serial)return;
      if(current!==this.sourceSignature){const upload=await this.service.upload(source,this.document);this.document=upload.document;this.revision=upload.revision;this.sourceSignature=current}
      if(serial!==this.serial)return;
      this.busy=false;
      const analysis=await this.task('analyze',{});if(serial!==this.serial)return;
      this.analysis=analysis;this.analysisStatus(true);
      this.device(analysis.models);this.sync();this.debugMask();if(analysis.faces.length&&!this.suppressNextAutoPreview)this.schedule(0);this.suppressNextAutoPreview=false;
    }catch(e){if(serial===this.serial){this.faceStatus('error','Pemindaian gagal. '+e.message);this.hooks.notice('Pemindaian gagal. '+e.message,true)}}finally{this.scanning=false;this.busy=false;this.hooks.lock(false);this.sync()}
  }
  device(models){$('ai-device').textContent='AI Retouch · '+(models?.device==='cuda'?'GPU acceleration':'CPU mode');if(models?.fallback)this.hooks.notice(models.fallback)}
  schedule(delay=220){if(this.pausedAfterSave||this.needsRepeatConsent()||!this.analysis?.faces.length)return;clearTimeout(this.timer);this.serial++;this.timer=setTimeout(()=>this.preview(),delay)}
  async preview(){
    if(this.pausedAfterSave||this.needsRepeatConsent()||!this.analysis?.faces.length||!this.visible)return;
    if(this.busy){this.pending=true;return}
    const serial=this.serial,settings=this.settings();
    try{
      const result=await this.task('preview',settings);if(serial!==this.serial)return;
      const image=new Image();image.src=result.url;await image.decode();if(serial!==this.serial)return;
      this.previewImage=image;this.previewSettingsKey=JSON.stringify(settings);this.temporary=true;this.hooks.preview(image);this.device(result.models);
      this.faceStatus('ready',`${result.faces} wajah ditemukan. Preview belum diterapkan.`);this.sync();
    }catch(e){if(serial===this.serial)this.hooks.notice(e.message,true)}
  }
  cancel(){
    clearTimeout(this.analysisTimer);
    clearTimeout(this.timer);this.pending=false;this.serial++;if(this.job)this.service.cancel(this.job).catch(()=>{});
    this.temporary=false;this.previewImage=null;this.previewSettingsKey=null;this.brush=false;this.drawing=false;this.strokes=[];this.hooks.restore();$('ai-brush-overlay').hidden=true;$('ai-mask-overlay').hidden=true;this.sync();
    if(this.scanning)this.faceStatus('cancelled','Pemindaian dibatalkan. Tekan Coba lagi untuk mengulang.');
    else if(this.analysis)this.analysisStatus();
  }
  async apply(){
    if(this.pausedAfterSave||this.needsRepeatConsent()||this.busy||!this.analysis?.faces.length)return;clearTimeout(this.timer);this.pending=false;const serial=++this.serial;
    try{
      const settings=this.settings();const result=await this.task('apply',settings);if(serial!==this.serial)return;
      const image=new Image();image.src=result.url;await image.decode();if(serial!==this.serial)return;
      this.snapshots.register(result,image);this.temporary=false;this.previewImage=null;this.previewSettingsKey=null;
      this.repeatApproved=false;this.repeatDismissed=false;
      this.suppressNextAutoPreview=true;this.pauseAfterSave();await this.hooks.apply(result,settings);this.hooks.notice('AI Retouch diterapkan sebagai satu langkah. Undo untuk kembali ke edit sebelumnya.');
    }catch(e){this.hooks.notice(e.message,true)}finally{this.sync()}
  }
  debugMask(){const name=$('ai-debug-mask').value,url=this.analysis?.masks?.[name];$('ai-mask-overlay').hidden=!this.visible||!url;if(url)$('ai-mask-overlay').src=url}
  pointerDown(){return false}
  pointerMove(){return false}
  pointerEnd(){}
}
