import {RetouchLibrary} from './library-client.mjs';
import {drawWipe} from './comparison.mjs';
import {resolutionPlan,workingOriginalSize} from './resolution.mjs';
import {FILTERS,stackFilter,stackAdjust,stackBackground,cancelPendingLook,EditHistory,freshState,signature,clamp,fitZoom,centeredCrop,moveCrop,resizeCrop,integerCrop,exportSize,renderGeometry,drawPreview,encodeExport} from './engine.mjs';
import {AIRetouchController} from './ai-controller.mjs';
import {AIEditController} from './ai-edit-controller.mjs';
import {AreaAdjust,areaHasChanges} from './area-adjust.mjs';
import {backgroundHasChanges,prepareBackground,backgroundImage} from './background.mjs';
import {HSL_COLORS,adjustHasChanges} from './hsl.mjs';

const $=id=>document.getElementById(id);
const viewport=$('viewport'),stage=$('image-stage'),preview=$('preview');
const history=new EditHistory();
const library=new RetouchLibrary();let historySaving=false;
let originalImage=null,currentPreview=null,editState=freshState(),fileName='',exportedSignature=signature(editState);
let resolutionPending=null,beforeReduced=null,beforeReducedKey='';
let tool='adjust',crop=null,zoom=1,pan={x:0,y:0},fitted=true,before=false,beforeView=null;
let gesture=null,confirmAction=null,loading=false,exporting=false,renderFrame=0,loadGeneration=0,dropDepth=0;
let geometryKey='',geometry=null,lastExportUrl=null;
let retouch=null,aiEdit=null,spacePan=false,aiBusy=false,renderRevision=0;
const names={crop:'Crop',adjust:'Adjust',filter:'Filter',background:'Background',retouch:'Retouch',ai:'AI Edit'};
const adjustmentNames=['exposure','brightness','contrast','saturation','highlights','shadows','temperature','tint','vibrance','whites','blacks','sharpness','vignette'];
let filterThumbKey='',filterThumbFrame=0;
const areas=new AreaAdjust({state:()=>editState,flush:flushAdjustment,commit,source:async()=>{await render();return geometry},
  size:()=>({width:currentPreview.width,height:currentPreview.height}),lock:value=>{aiBusy=value;sync()},refresh:sync,redraw:()=>{if(currentPreview)showPixels()},render});
let hslColor='red';
for(const color of HSL_COLORS){
  const button=document.createElement('button');button.type='button';button.dataset.hslColor=color.id;button.setAttribute('aria-pressed',String(color.id===hslColor));
  const dot=document.createElement('span');dot.className='hsl-dot';dot.style.setProperty('--hsl-swatch',color.color);dot.setAttribute('aria-hidden','true');
  const label=document.createElement('span');label.textContent=color.name;button.append(dot,label);$('hsl-colors').append(button);
  button.onclick=()=>{flushAdjustment();hslColor=color.id;sync()};
}
function syncHSL(settings){
  document.querySelectorAll('[data-hsl-color]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.hslColor===hslColor)));
  const selected=settings.hsl?.[hslColor]||{};
  for(const key of ['hue','saturation','luminance']){$('hsl-'+key).value=selected[key]??0;$('hsl-'+key+'-value').textContent=(selected[key]??0)+(key==='hue'?'°':'')}
  $('hsl-selection').textContent=HSL_COLORS.find(c=>c.id===hslColor).name+' · '+({all:'Semua',person:'Orang',background:'Latar'}[areas.target]);
}
for(const key of ['hue','saturation','luminance']){
  const input=$('hsl-'+key);
  input.oninput=()=>{
    if(!originalImage||before||aiBusy||loading||exporting||historySaving)return;
    const settings=areas.current(editState);settings.hsl??={};settings.hsl[hslColor]??={};
    settings.hsl[hslColor][key]=clamp(Number(input.value),Number(input.min),Number(input.max));
    $('hsl-'+key+'-value').textContent=input.value+(key==='hue'?'°':'');schedulePreview();
  };
  input.onchange=flushAdjustment;input.onblur=()=>{flushAdjustment();sync()};
}
$('area-select').onchange=()=>areas.select($('area-select').value);
let areaStatusTimer=null,areaStatusKey='',areaStatusExpired=false;
function syncAreaStatus(){
  const statuses=[$('area-status'),$('background-status')],tone=areas.statusTone;
  const show=(text,kind,hidden=false)=>{for(const status of statuses){status.textContent=text;status.dataset.tone=kind;status.hidden=hidden}};
  if(areas.busy){
    clearTimeout(areaStatusTimer);areaStatusKey='';areaStatusExpired=false;
    show('Memisahkan area…','loading');return;
  }
  if(tone==='ready'&&editState.area?.mask){
    const key=areas.serial+':'+areas.status;
    if(key!==areaStatusKey){
      clearTimeout(areaStatusTimer);areaStatusKey=key;areaStatusExpired=false;
      areaStatusTimer=setTimeout(()=>{areaStatusExpired=true;for(const status of statuses)status.hidden=true},2200);
    }
    show('Area siap','ready',areaStatusExpired);return;
  }
  clearTimeout(areaStatusTimer);areaStatusKey='';areaStatusExpired=false;
  const visible=['error','warning'].includes(tone)&&!!areas.status;
  show(visible?areas.status:'',tone||'',!visible);
}
$('area-show').onclick=()=>{areas.showMask=!areas.showMask;sync();showPixels()};
for(const [id,add] of [['area-add-person',true],['area-add-background',false]])$(id).onclick=()=>{
  if(areas.target==='all')return;
  const mode=add?areas.target:(areas.target==='person'?'background':'person');
  areas.mode=areas.mode===mode?null:mode;areas.showMask=true;sync();showPixels();
};
$('area-refine').ontoggle=()=>{if(!$('area-refine').open){areas.mode=null;sync()}};
let backgroundThumbnailKey=null;
let backgroundPaused=false,backgroundDismissed=false,backgroundApprovedKey=null;
const backgroundAppliedKey=()=>JSON.stringify(editState.operations.filter(op=>op.background));
function resetBackgroundRound(){
  backgroundPaused=false;backgroundDismissed=false;backgroundApprovedKey=null;$('background-again-notice').hidden=true;
}
async function enterBackground(){
  if(tool!=='background'||!originalImage||resolutionPending||loading||exporting||aiBusy||historySaving)return;
  const key=backgroundAppliedKey();
  if(key!=='[]'&&backgroundApprovedKey!==key){
    backgroundPaused=true;
    if(!backgroundDismissed){$('notice').hidden=true;$('background-again-notice').hidden=false}
    sync();return;
  }
  if(key==='[]'){backgroundPaused=false;backgroundDismissed=false;backgroundApprovedKey=null}
  if(!backgroundPaused)await areas.select('background');
}
$('background-again-decline').onclick=()=>{
  backgroundDismissed=true;$('background-again-notice').hidden=true;sync();
};
$('background-again-accept').onclick=async()=>{
  if(tool!=='background'||loading||exporting||aiBusy||historySaving||resolutionPending)return;
  const key=backgroundAppliedKey();$('background-again-notice').hidden=true;backgroundDismissed=true;
  await areas.select('background',{force:true});
  if(areas.statusTone==='ready'&&editState.area?.mask){backgroundApprovedKey=key;backgroundPaused=false;backgroundDismissed=false}
  else backgroundPaused=true;
  sync();
};
function syncBackground(ready){
  ready=ready&&!backgroundPaused;
  $('background-fields').disabled=!ready||before;
  const bg=editState.background;
  document.querySelectorAll('[data-background]').forEach(b=>{b.disabled=!ready||!editState.area?.mask;b.setAttribute('aria-pressed',String(bg?.mode===b.dataset.background))});
  document.querySelectorAll('[data-background-option]').forEach(p=>p.hidden=p.dataset.backgroundOption!==bg?.mode);
  for(const [key,fallback,unit] of [['blur',35,''],['scale',100,'%'],['x',50,'%'],['y',50,'%'],['feather',2,' px']]){
    $('background-'+key).value=bg?.[key]??fallback;$('background-'+key+'-value').textContent=$('background-'+key).value+unit;
  }
  $('background-color').value=bg?.color||'#e6eddd';$('background-color-value').textContent=$('background-color').value.toUpperCase();
  const image=backgroundImage(bg?.image);$('background-image-preview').hidden=!image;
  $('background-file-name').textContent=bg?.name||'';
  if(image&&backgroundThumbnailKey!==bg.image){
    const canvas=$('background-thumbnail'),ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);
    const scale=Math.max(canvas.width/image.naturalWidth,canvas.height/image.naturalHeight),w=image.naturalWidth*scale,h=image.naturalHeight*scale;
    ctx.drawImage(image,(canvas.width-w)/2,(canvas.height-h)/2,w,h);backgroundThumbnailKey=bg.image;
  }else if(!image){backgroundThumbnailKey=null;$('background-thumbnail').getContext('2d').clearRect(0,0,64,48)}
  $('background-refine').hidden=!editState.area?.mask;
  $('background-show').setAttribute('aria-pressed',String(areas.showMask));
  $('background-person').setAttribute('aria-pressed',String(areas.mode==='background'));$('background-remove').setAttribute('aria-pressed',String(areas.mode==='person'));
}
function backgroundSettings(){
  if(backgroundPaused||!editState.area?.mask)return null;
  return editState.background??={mask:editState.area.mask,mode:'blur',blur:35,color:'#e6eddd',feather:2,scale:100,x:50,y:50};
}
document.querySelectorAll('[data-background]').forEach(button=>button.onclick=()=>{
  flushAdjustment();const bg=backgroundSettings();if(!bg)return;bg.mode=button.dataset.background;commit();render();
});
for(const key of ['blur','scale','x','y','feather','color']){
  const input=$('background-'+key);
  input.oninput=()=>{const bg=backgroundSettings();if(!bg)return;bg[key]=key==='color'?input.value:Number(input.value);schedulePreview();sync()};
  input.onchange=()=>{flushAdjustment();commit()};
}
$('background-open').onclick=()=>{$('background-file').value='';$('background-file').click()};
$('background-file').onchange=async()=>{
  const file=$('background-file').files[0];if(!file)return;
  if(!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size>256*1024*1024){notice('Pilih gambar JPG, PNG, atau WebP maksimal 256 MB.',true);return}
  const generation=loadGeneration;let image,url;
  loading=true;sync();
  try{
    url=URL.createObjectURL(file);image=new Image();image.src=url;await image.decode();
    if(image.naturalWidth*image.naturalHeight>50_000_000)throw Error('Gambar latar melebihi 50 MP.');
    const scale=Math.min(1,2048/Math.max(image.naturalWidth,image.naturalHeight));
    const c=document.createElement('canvas');c.width=Math.max(1,Math.round(image.naturalWidth*scale));c.height=Math.max(1,Math.round(image.naturalHeight*scale));
    const ctx=c.getContext('2d');ctx.imageSmoothingQuality='high';ctx.drawImage(image,0,0,c.width,c.height);
    const data=c.toDataURL('image/png');c.width=0;
    if(data.length>24*1024*1024)throw Error('Gambar latar terlalu besar untuk disimpan.');
    if(generation!==loadGeneration)return;
    const bg=backgroundSettings();if(!bg)return;Object.assign(bg,{mode:'image',image:data,name:file.name,scale:100,x:50,y:50});commit();await render();
  }catch(e){notice(e.message,true)}finally{if(url)URL.revokeObjectURL(url);loading=false;sync()}
};
$('background-show').onclick=()=>{areas.target='background';areas.showMask=!areas.showMask;sync();showPixels()};
for(const [id,mode] of [['background-person','background'],['background-remove','person']])$(id).onclick=()=>{areas.target='background';areas.mode=areas.mode===mode?null:mode;areas.showMask=true;sync();showPixels()};
$('background-brush').oninput=()=>{$('area-brush-size').value=$('background-brush').value;$('background-brush-value').textContent=$('background-brush').value+' px'};
$('background-refine').ontoggle=()=>{if(!$('background-refine').open){areas.mode=null;sync()}};
for(const filter of FILTERS){
  const button=document.createElement('button');button.type='button';button.dataset.filter=filter.id;button.setAttribute('aria-pressed',String(filter.id==='none'));
  const thumb=document.createElement('canvas');thumb.className='filter-thumb';thumb.width=160;thumb.height=100;thumb.setAttribute('aria-hidden','true');
  const label=document.createElement('span');label.textContent=filter.name;button.append(thumb,label);$('filter-grid').append(button);
}
let comparisonSource=null,comparisonSourceKey=null,comparisonCommittedKey=null,comparisonEnabled=true;
function clearComparison(){
  if(comparisonSource){comparisonSource.width=0;comparisonSource.height=0}
  comparisonSource=null;comparisonSourceKey=null;comparisonCommittedKey=null;
  $('retouch-comparison').hidden=true;$('retouch-divider').hidden=true;
}
function captureComparison(){
  const key=signature(editState);
  if(comparisonSource&&comparisonSourceKey===key)return;
  clearComparison();comparisonSource=document.createElement('canvas');
  comparisonSource.width=currentPreview.width;comparisonSource.height=currentPreview.height;
  comparisonSource.getContext('2d').drawImage(currentPreview,0,0);
  comparisonSourceKey=key;comparisonEnabled=true;$('retouch-comparison-range').value=50;
}
function drawComparison(source){
  const available=tool==='retouch'&&!before&&!!comparisonSource&&(retouch?.temporary||comparisonCommittedKey===signature(editState));
  $('retouch-comparison').hidden=!available;
  $('retouch-divider').hidden=!available||!comparisonEnabled;
  $('retouch-comparison-toggle').setAttribute('aria-pressed',String(comparisonEnabled));
  $('retouch-comparison-toggle').title=comparisonEnabled?'Tampilkan hasil penuh':'Tampilkan perbandingan';
  if(!available||!comparisonEnabled)return false;
  const percent=Number($('retouch-comparison-range').value);
  drawWipe(preview.getContext('2d'),comparisonSource,source,preview.width,preview.height,percent);
  $('retouch-divider').style.left=percent+'%';return true;
}
let comparisonFrame=0;
function scheduleComparison(){if(!comparisonFrame)comparisonFrame=requestAnimationFrame(()=>{comparisonFrame=0;if(currentPreview)showPixels()})}
$('retouch-comparison-range').oninput=scheduleComparison;
$('retouch-comparison-toggle').onclick=()=>{comparisonEnabled=!comparisonEnabled;showPixels()};
const comparisonHandle=$('retouch-divider-handle');let comparisonPointer=null;
function moveComparison(event){
  const rect=stage.getBoundingClientRect();
  $('retouch-comparison-range').value=clamp((event.clientX-rect.left)/rect.width*100,0,100);
  scheduleComparison();
}
comparisonHandle.addEventListener('pointerdown',event=>{
  event.stopPropagation();event.preventDefault();if(event.button!==0)return;
  comparisonPointer=event.pointerId;comparisonHandle.setPointerCapture(event.pointerId);moveComparison(event);
});
comparisonHandle.addEventListener('pointermove',event=>{if(comparisonPointer===event.pointerId){event.stopPropagation();moveComparison(event)}});
for(const event of ['pointerup','pointercancel','lostpointercapture'])comparisonHandle.addEventListener(event,e=>{e.stopPropagation();comparisonPointer=null});
let noticeTimer=null;
function notice(text,error=false,tone=null,duration=0){clearTimeout(noticeTimer);$('notice-text').textContent=text;$('notice').hidden=false;$('notice').classList.toggle('error',error);$('notice').classList.toggle('warning',tone==='warning');$('export-download').hidden=true;if(duration)noticeTimer=setTimeout(()=>$('notice').hidden=true,duration)}
$('notice-close').onclick=()=>{clearTimeout(noticeTimer);$('notice').hidden=true};
function dirty(){return !!originalImage&&signature(editState)!==exportedSignature&&signature(editState)!==library.signature}
function sync(){
  const ready=!!originalImage&&!loading&&!exporting&&!aiBusy&&!historySaving&&!resolutionPending;
  $('save-history').disabled=!ready;
  $('filename').textContent=fileName||'Belum ada foto';$('dirty').hidden=!dirty();
  $('undo').disabled=!ready||!history.canUndo;$('redo').disabled=!ready||!history.canRedo;
  $('reset').disabled=!ready||signature(editState)===signature(freshState());$('export').disabled=!ready;
  $('open').disabled=loading||exporting||aiBusy||historySaving;$('open-empty').disabled=loading||aiBusy||historySaving;
  document.querySelectorAll('[data-tool]').forEach(button=>button.disabled=aiBusy||historySaving);
  for(const id of ['adjust-fields','crop-fields','filter-fields','background-fields'])$(id).disabled=!ready||before;
  for(const id of ['zoom-in','zoom-out','zoom-value','fit','center','before'])$(id).disabled=!ready;
  $('no-photo-note').hidden=!!originalImage;
  if(!editState.area?.mask)areas.target='all';
  const activeAdjust=areas.current(editState);syncHSL(activeAdjust);
  adjustmentNames.forEach(name=>{$(name).value=activeAdjust[name]??0;$(name+'-number').value=activeAdjust[name]??0});
  $('area-select').value=areas.target;
  $('area-show').disabled=!ready||!editState.area?.mask||areas.target==='all';$('area-show').setAttribute('aria-pressed',String(areas.showMask));
  syncAreaStatus();
  document.querySelector('.adjust-area').setAttribute('aria-busy',String(areas.busy));
  $('area-refine').hidden=!editState.area?.mask||areas.target==='all';
  const selectedArea=areas.target==='person'?'orang':'latar';
  for(const [id,add] of [['area-add-person',true],['area-add-background',false]]){
    const mode=add?areas.target:(areas.target==='person'?'background':'person');
    $(id).setAttribute('aria-pressed',String(areas.mode===mode));
    $(id).title=`${add?'Tambah':'Kurangi'} area ${selectedArea}`;$(id).setAttribute('aria-label',$(id).title);
  }
  document.querySelectorAll('[data-filter]').forEach(b=>{const active=b.dataset.filter===editState.filter;b.classList.toggle('selected',active);b.setAttribute('aria-pressed',String(active))});
  $('filter-intensity').value=editState.filterIntensity??100;$('filter-intensity-value').textContent=($('filter-intensity').value)+'%';$('filter-intensity').disabled=editState.filter==='none';
  syncBackground(ready);
  const applicable={background:!backgroundPaused&&backgroundHasChanges(editState.background),filter:editState.filter!=='none'&&(editState.filterIntensity??100)>0,adjust:adjustHasChanges(editState.adjust)||areaHasChanges(editState.area),crop:!!crop,retouch:!!retouch?.analysis?.faces.length&&!retouch?.busy,ai:!!aiEdit?.canRun()&&!aiEdit?.busy};
  $('filter-apply').hidden=!(tool in applicable);$('filter-apply').disabled=!ready||before||!applicable[tool];
  $('filter-apply').setAttribute('aria-label','Apply '+(names[tool]||''));
  const cancellable=tool==='background'?!!editState.background:tool==='ai'?!!(aiEdit?.strokes.length||aiEdit?.busy||aiEdit?.temporary):tool==='retouch'?!!(retouch?.analysis||retouch?.busy||retouch?.temporary):tool==='crop'?!!crop:tool==='adjust'?applicable.adjust:tool==='filter'&&(editState.filter!=='none'||(editState.filterIntensity??100)!==100);
  $('edit-cancel').hidden=!(tool in applicable);
  $('edit-cancel').disabled=!originalImage||loading||exporting||before||(aiBusy&&!['retouch','ai'].includes(tool))||!cancellable;
  $('edit-cancel').setAttribute('aria-label','Cancel '+(names[tool]||''));
  for(const id of ['resolution-accept','resolution-decline'])$(id).disabled=loading||exporting||aiBusy||historySaving;
  for(const id of ['background-again-accept','background-again-decline'])$(id).disabled=loading||exporting||aiBusy||historySaving||!!resolutionPending;
  retouch?.sync();if(historySaving){$('ai-controls').disabled=true;$('edit-fields').disabled=true}
}
function constrainPan(){
  const w=preview.width*zoom,h=preview.height*zoom;
  const maxX=Math.max(0,(w-viewport.clientWidth)/2+32),maxY=Math.max(0,(h-viewport.clientHeight)/2+32);
  pan.x=clamp(pan.x,-maxX,maxX);pan.y=clamp(pan.y,-maxY,maxY);
}
function updateView(){
  constrainPan();stage.style.width=preview.width+'px';stage.style.height=preview.height+'px';
  stage.style.transform=`translate(-50%,-50%) translate(${pan.x}px,${pan.y}px) scale(${zoom})`;
  stage.style.setProperty('--comparison-zoom',zoom);stage.style.setProperty('--comparison-inverse',1/zoom);
  stage.style.setProperty('--handle-size',`${14/zoom}px`);stage.style.setProperty('--crop-line',`${1.5/zoom}px`);
  $('zoom-value').textContent=(zoom<.1?(zoom*100).toFixed(1):Math.round(zoom*100))+'%';
  viewport.classList.toggle('loaded',!!originalImage);viewport.classList.toggle('cropping',tool==='crop'&&!before&&!!originalImage);
  updateCrop();
}
function fit(){if(!originalImage)return;zoom=fitZoom(preview.width,preview.height,viewport.clientWidth,viewport.clientHeight);pan={x:0,y:0};fitted=true;updateView()}
function setZoom(value,point=null){
  if(!originalImage)return;
  const old=zoom;zoom=clamp(value,.001,8);
  if(point){pan.x=point.x-(point.x-pan.x)*zoom/old;pan.y=point.y-(point.y-pan.y)*zoom/old}
  fitted=false;updateView();
}
function ratio(){return $('crop-ratio').value==='original'?originalImage.naturalWidth/originalImage.naturalHeight:Number($('crop-ratio').value)||0}
function newCrop(){if(originalImage)crop=centeredCrop(currentPreview.width,currentPreview.height,ratio());updateCrop()}
function updateCrop(){
  const visible=!!originalImage&&tool==='crop'&&!before&&!!crop;
  $('crop-overlay').hidden=!visible;
  if(!visible)return;
  const box=$('crop-box');box.style.left=crop.x+'px';box.style.top=crop.y+'px';box.style.width=crop.w+'px';box.style.height=crop.h+'px';
  const r=integerCrop(crop,currentPreview.width,currentPreview.height);$('crop-size').textContent=`${r.w} × ${r.h} px`;
  document.querySelectorAll('[data-ratio]').forEach(b=>b.classList.toggle('selected',b.dataset.ratio===$('crop-ratio').value));
}
async function render(refit=false){
  if(!originalImage)return;
  const revision=++renderRevision;
  await prepareBackground(editState);await areas.prepare(editState);if(revision!==renderRevision)return;
  const snapshot=editState.operations.findLast(op=>op.type==='retouch');
  if(snapshot&&!retouch.snapshots.get(snapshot.id)){
    loading=true;sync();
    try{await retouch.snapshots.ensure(snapshot.id)}catch(e){notice(e.message,true);return}
    finally{if(revision===renderRevision){loading=false;sync()}}
    if(revision!==renderRevision)return;
  }
  const key=JSON.stringify(editState.operations);
  if(!geometry||key!==geometryKey){
    if(geometry){geometry.width=0;geometry.height=0}
    geometry=renderGeometry(originalImage,editState.operations,id=>retouch.snapshots.get(id),(id,ops)=>areas.mask(editState,id,ops));geometryKey=key;
  }
  if(!currentPreview)currentPreview=document.createElement('canvas');
  drawPreview(geometry,editState,currentPreview,id=>areas.mask(editState,id));
  showPixels();if(refit)fit();else updateView();sync();
  scheduleFilterThumbs();
}
function scheduleFilterThumbs(){
  if(tool!=='filter'||!originalImage||!geometry||filterThumbFrame)return;
  filterThumbFrame=requestAnimationFrame(()=>{
    filterThumbFrame=0;if(tool!=='filter'||!geometry)return;
    const key=geometryKey+JSON.stringify(editState.adjust)+JSON.stringify(editState.area)+JSON.stringify(editState.background)+(editState.filterIntensity??100);
    if(key===filterThumbKey)return;
    const small=document.createElement('canvas'),scale=Math.min(1,160/Math.max(geometry.width,geometry.height));
    small.width=Math.max(1,Math.round(geometry.width*scale));small.height=Math.max(1,Math.round(geometry.height*scale));
    small.getContext('2d').drawImage(geometry,0,0,small.width,small.height);
    for(const button of document.querySelectorAll('[data-filter]'))drawPreview(small,{...editState,filter:button.dataset.filter},button.querySelector('canvas'),id=>areas.mask(editState,id));
    small.width=0;small.height=0;filterThumbKey=key;
  });
}
function schedulePreview(){
  if(renderFrame)return;
  renderFrame=requestAnimationFrame(()=>{renderFrame=0;render().catch(e=>notice(e.message,true))});
}
function originalForBefore(){
  const size=workingOriginalSize(originalImage.naturalWidth,originalImage.naturalHeight,editState.operations);
  if(size.width===originalImage.naturalWidth&&size.height===originalImage.naturalHeight)return originalImage;
  const key=size.width+'x'+size.height;
  if(!beforeReduced||beforeReducedKey!==key){
    if(beforeReduced){beforeReduced.width=0;beforeReduced.height=0}
    beforeReduced=document.createElement('canvas');beforeReduced.width=size.width;beforeReduced.height=size.height;
    const ctx=beforeReduced.getContext('2d');ctx.imageSmoothingEnabled=true;ctx.imageSmoothingQuality='high';ctx.drawImage(originalImage,0,0,size.width,size.height);beforeReducedKey=key;
  }
  return beforeReduced;
}
function updateResolutionNotice(){
  if(!resolutionPending)return;
  const {before,after,reduction}=resolutionPending;
  $('resolution-question').textContent='Atur pengurangan lebar dan tinggi agar pengeditan lebih ringan.';
  $('resolution-value').textContent=`${reduction}%`;
  $('resolution-accept').title=reduction?`Kurangi resolusi ${reduction}%`:'Gunakan ukuran asli';
  $('resolution-accept').setAttribute('aria-label',$('resolution-accept').title);
  $('resolution-sizes').textContent=`${before.width} × ${before.height} px → ${after.width} × ${after.height} px`;
}
function offerResolution(){
  resolutionPending=editState.operations.some(op=>op.type==='resize'&&op.reason==='performance')?null:resolutionPlan(currentPreview.width,currentPreview.height);
  $('resolution-notice').hidden=!resolutionPending;
  if(resolutionPending){
    $('retouch-again-notice').hidden=true;
    $('background-again-notice').hidden=true;
    $('resolution-range').value=50;
    $('notice').hidden=true;updateResolutionNotice();
  }
  sync();
}
$('resolution-range').oninput=()=>{
  if(!resolutionPending)return;
  const {before}=resolutionPending;
  resolutionPending=resolutionPlan(before.width,before.height,Number($('resolution-range').value));
  updateResolutionNotice();
};
$('resolution-decline').onclick=()=>{
  if(loading||exporting||aiBusy||historySaving)return;
  resolutionPending=null;$('resolution-notice').hidden=true;sync();retouch?.photoLoaded();enterBackground();
};
$('resolution-accept').onclick=async()=>{
  if(!resolutionPending||loading||exporting||aiBusy||historySaving)return;
  const {after,scale,reduction}=resolutionPending;
  resolutionPending=null;$('resolution-notice').hidden=true;
  if(!reduction){sync();retouch?.photoLoaded();await enterBackground();return}
  try{
    clearComparison();await operation({type:'resize',reason:'performance',width:after.width,height:after.height,scale});
    retouch?.photoLoaded();
    const saved=library.signature===signature(editState);
    notice(`Resolusi kerja dikurangi menjadi ${after.width} × ${after.height} px. Foto unggahan asli tidak diubah.`+(saved?'':' Tekan Save untuk menyimpan ke Riwayat.'),!saved);
    await enterBackground();
  }catch(error){notice('Pengurangan resolusi gagal. '+error.message,true);sync()}
};
function showPixels(){
  const source=before?originalForBefore():(tool==='retouch'&&retouch?.temporary?retouch.previewImage:tool==='ai'&&aiEdit?.temporary?aiEdit.previewImage:currentPreview);
  const width=before?(source.naturalWidth||source.width):currentPreview.width,height=before?(source.naturalHeight||source.height):currentPreview.height;
  if(preview.width!==width)preview.width=width;if(preview.height!==height)preview.height=height;
  if(!drawComparison(source)){const ctx=preview.getContext('2d');ctx.clearRect(0,0,width,height);ctx.drawImage(source,0,0)}
  if(['adjust','background'].includes(tool)&&!before)areas.overlay(preview.getContext('2d'),editState,width,height);
  $('dimensions').textContent=`${preview.width} × ${preview.height} px${before?' · Original':''}`;
}
function commit(){
  if(editState.areaMasks){
    const used=new Set(editState.operations.filter(op=>op.area?.mask).map(op=>op.area.mask));if(editState.area?.mask)used.add(editState.area.mask);if(editState.background?.mask)used.add(editState.background.mask);for(const op of editState.operations)if(op.background?.mask)used.add(op.background.mask);
    for(const id of Object.keys(editState.areaMasks))if(!used.has(id))delete editState.areaMasks[id];
  }
  if(history.push(editState)){retouch?.invalidate();aiEdit?.invalidate()}sync();
}
function flushAdjustment(){if(renderFrame){cancelAnimationFrame(renderFrame);renderFrame=0;render()}if(originalImage)commit()}
function selectTool(next,explicit=false){
  areas.pointerUp();areas.mode=null;
  if(tool==='background'&&next!==tool){$('background-again-notice').hidden=true;backgroundDismissed=false}
  flushAdjustment();if(before)setBefore(false);tool=next;
  document.querySelectorAll('[data-tool]').forEach(b=>{const active=b.dataset.tool===tool;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active))});
  document.querySelectorAll('[data-panel]').forEach(p=>p.hidden=p.dataset.panel!==tool);
  $('tool-title').textContent=names[tool];if(tool==='crop')newCrop();else crop=null;updateView();
  if(currentPreview)showPixels();
  if(explicit&&tool==='retouch')retouch?.resumeAfterSave();
  retouch?.show(tool==='retouch');
  aiEdit?.show(tool==='ai');
  scheduleFilterThumbs();
  if(tool==='background')enterBackground();
  if(matchMedia('(max-width:900px)').matches)togglePanel(true);
  sync();
}
document.querySelectorAll('[data-tool]').forEach(b=>b.onclick=()=>selectTool(b.dataset.tool,true));
function togglePanel(open){$('context-panel').classList.toggle('open',open);$('panel-toggle').setAttribute('aria-expanded',String(open))}
$('panel-toggle').onclick=()=>togglePanel(!$('context-panel').classList.contains('open'));
$('panel-close').onclick=()=>togglePanel(false);
function ask(title,copy,label,action){confirmAction=action;$('confirm-title').textContent=title;$('confirm-copy').textContent=copy;$('confirm-apply').textContent=label;$('confirm-dialog').showModal()}
$('confirm-cancel').onclick=()=>{$('confirm-dialog').close();confirmAction=null};
$('confirm-dialog').addEventListener('cancel',()=>confirmAction=null);
$('confirm-apply').onclick=()=>{const action=confirmAction;confirmAction=null;$('confirm-dialog').close();action?.()};
function requestOpen(){if(loading||exporting||aiBusy)return;$('file-input').value='';$('file-input').click()}
$('open').onclick=requestOpen;$('open-empty').onclick=requestOpen;
async function loadFile(file){
  if(!file)return;
  if(!/\.(jpe?g|png|webp)$/i.test(file.name)||!['image/jpeg','image/png','image/webp',''].includes(file.type)){notice('Pilih foto JPG, JPEG, PNG, atau WEBP.',true);return}
  if(file.size>256*1024*1024||!file.size){notice('Foto kosong atau melebihi batas 256 MB.',true);return}
  if(dirty()){
    ask('Buka foto lain?','Perubahan pada foto saat ini belum disimpan. Gunakan Simpan atau Export agar dapat dibuka kembali.','Buka foto',()=>decodeFile(file));return;
  }
  await decodeFile(file);
}
async function saveWorkspace(){
  if(!originalImage||historySaving)return false;
  historySaving=true;retouch?.pauseAfterSave();sync();
  try{
    const state=structuredClone(editState),settings={retouch:{...retouch.settings(),manual:Object.fromEntries(['smooth','restore','strength'].map(key=>[key,Number($('ai-'+key).value)]))},ai:aiEdit.settings()};
    const ids=new Set(state.operations.filter(op=>op.type==='retouch').map(op=>op.id));
    const snapshots=[...ids].map(id=>{const record=retouch.snapshots.records.get(id);if(!record)throw Error('Snapshot AI belum tersedia.');return {id,url:record.url}});
    const result=await new Promise(resolve=>currentPreview.toBlob(resolve,'image/png'));if(!result)throw Error('Hasil tidak dapat disimpan.');
    await library.save({name:fileName,state,settings,tool,snapshots,result});
    return true;
  }catch(error){notice('Riwayat gagal disimpan. '+error.message+' Tekan Save untuk mencoba lagi.',true);return false}
  finally{historySaving=false;sync()}
}
$('save-history').onclick=async()=>{retouch.cancel();retouch.pauseAfterSave();aiEdit.cancel();flushAdjustment();await render();if(await saveWorkspace())notice('Berhasil disimpan.')}
async function decodeFile(file,{fromHistory=false}={}){
  const generation=++loadGeneration;loading=true;sync();let url;
  try{
    url=URL.createObjectURL(file);const image=new Image();image.src=url;await image.decode();
    if(generation!==loadGeneration)return;
    if(!image.naturalWidth||image.naturalWidth*image.naturalHeight>50_000_000)throw new Error('Foto melebihi batas 50 MP atau tidak dapat dibaca.');
    if(before)setBefore(false);
    resolutionPending=null;$('resolution-notice').hidden=true;if(beforeReduced){beforeReduced.width=0;beforeReduced.height=0;beforeReduced=null}beforeReducedKey='';
    areas.reset();resetBackgroundRound();originalImage=image;fileName=file.name;library.reset(file);history.reset();editState=history.current;exportedSignature=signature(editState);
    clearComparison();await retouch?.resetDocument();
    await aiEdit?.resetDocument();
    if(lastExportUrl){URL.revokeObjectURL(lastExportUrl);lastExportUrl=null}
    geometryKey='';filterThumbKey='';if(geometry){geometry.width=0;geometry.height=0;geometry=null}
    $('empty').hidden=true;stage.hidden=false;$('notice').hidden=true;loading=false;
    await render(true);if(tool==='crop')newCrop();viewport.focus();if(!fromHistory){offerResolution();if(!resolutionPending){retouch?.photoLoaded();await enterBackground()}}
    $('export-name').value=file.name.replace(/\.[^.]+$/,'')+'-edited';
  }catch(e){notice('Foto tidak dapat dibuka. '+e.message,true)}
  finally{if(url)URL.revokeObjectURL(url);if(generation===loadGeneration){loading=false;sync()}}
}
$('file-input').addEventListener('change',()=>loadFile($('file-input').files[0]));
window.addEventListener('dragover',e=>e.preventDefault());
window.addEventListener('drop',e=>e.preventDefault());
viewport.addEventListener('dragenter',e=>{e.preventDefault();dropDepth++;$('drop-hint').hidden=false});
viewport.addEventListener('dragleave',()=>{if(--dropDepth<=0){dropDepth=0;$('drop-hint').hidden=true}});
viewport.addEventListener('dragover',e=>{e.preventDefault();e.dataTransfer.dropEffect='copy'});
viewport.addEventListener('drop',e=>{e.preventDefault();dropDepth=0;$('drop-hint').hidden=true;if(loading||exporting||aiBusy)return;if(e.dataTransfer.files.length!==1){notice('Buka satu foto pada satu waktu.',true);return}loadFile(e.dataTransfer.files[0])});

adjustmentNames.forEach(name=>{
  for(const input of [$(name),$(name+'-number')]){
    input.addEventListener('input',()=>{
      if(!originalImage||before)return;
      const value=Number(input.value);if(input.value===''||!Number.isFinite(value))return;
      const settings=areas.current(editState);settings[name]=clamp(value,Number(input.min),Number(input.max));
      const other=input===$(name)?$(name+'-number'):$(name);other.value=settings[name];schedulePreview();
    });
    input.addEventListener('change',flushAdjustment);
    input.addEventListener('blur',()=>{flushAdjustment();sync()});
  }
});
$('adjust-reset').onclick=()=>{flushAdjustment();if(areas.target==='all')editState.adjust=freshState().adjust;else editState.area[areas.target]={};commit();render()};
document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{flushAdjustment();editState.filter=b.dataset.filter;commit();render()});
$('filter-intensity').oninput=()=>{editState.filterIntensity=Number($('filter-intensity').value);$('filter-intensity-value').textContent=editState.filterIntensity+'%';schedulePreview()};
$('filter-intensity').onchange=flushAdjustment;
$('filter-intensity').onblur=flushAdjustment;
$('edit-cancel').onclick=async()=>{
  if(!originalImage||loading||exporting||before||(aiBusy&&!['retouch','ai'].includes(tool)))return;
  if(tool==='crop'){$('crop-cancel').click();return}
  if(tool==='retouch'){retouch?.cancel();sync();return}
  if(tool==='ai'){aiEdit?.cancel();sync();return}
  flushAdjustment();const next=cancelPendingLook(editState,tool);if(!next)return;
  editState=next;commit();await render();await saveWorkspace();
  notice(tool==='background'?'Perubahan Background dibatalkan.':tool==='adjust'?'Penyesuaian yang belum di-Apply dibatalkan.':'Filter yang belum di-Apply dibatalkan.');
};
$('filter-apply').onclick=async()=>{
  if(!originalImage||loading||exporting||aiBusy||historySaving||before)return;
  if(tool==='crop'){$('crop-apply').click();return}
  if(tool==='retouch'){await retouch?.apply();return}
  if(tool==='ai'){await aiEdit?.apply();return}
  if(!['filter','adjust','background'].includes(tool))return;
  if(tool==='background'&&backgroundPaused)return;
  flushAdjustment();
  if(editState.operations.length>=500){notice('Batas 500 operasi tercapai. Export lalu buka hasil sebagai foto baru.',true);return}
  const next=tool==='background'?stackBackground(editState):tool==='adjust'?stackAdjust(editState):stackFilter(editState);if(!next)return;
  if(next.operations.at(-1)?.background){
    backgroundPaused=true;backgroundDismissed=true;backgroundApprovedKey=null;
    $('background-again-notice').hidden=true;areas.mode=null;areas.showMask=false;
  }
  editState=next;commit();await render();
  notice(tool==='background'?'Background diterapkan.':tool==='adjust'?'Penyesuaian diterapkan. Kontrol kembali netral untuk penyesuaian berikutnya.':'Filter diterapkan. Pilih filter lain untuk menumpuk efek berikutnya.');
};
async function operation(op){
  if(!originalImage||exporting||aiBusy||historySaving)return;flushAdjustment();if(before)setBefore(false);
  if(editState.operations.length>=500){notice('Batas 500 operasi geometris tercapai. Export lalu buka hasil sebagai foto baru.',true);return}
  editState.operations.push(op);commit();await render(true);if(tool==='crop')newCrop();await saveWorkspace();
}
$('rotate-left').onclick=()=>operation({type:'rotate',direction:-1});$('rotate-right').onclick=()=>operation({type:'rotate',direction:1});
$('flip-x').onclick=()=>operation({type:'flip',axis:'x'});$('flip-y').onclick=()=>operation({type:'flip',axis:'y'});
$('crop-ratio').onchange=newCrop;
document.querySelectorAll('[data-ratio]').forEach(b=>b.onclick=()=>{$('crop-ratio').value=b.dataset.ratio;newCrop()});
$('crop-cancel').onclick=()=>{crop=null;selectTool('adjust')};
$('crop-apply').onclick=async()=>{if(!crop)return;const r=integerCrop(crop,currentPreview.width,currentPreview.height);await operation({type:'crop',...r});selectTool('adjust')};
function navigateHistory(direction){
  if(!originalImage||exporting||aiBusy||historySaving)return;flushAdjustment();if(before)setBefore(false);
  retouch?.invalidate();
  aiEdit?.invalidate();
  editState=direction<0?history.undo():history.redo();
  $('background-again-notice').hidden=true;
  backgroundPaused=backgroundAppliedKey()!=='[]'&&backgroundApprovedKey!==backgroundAppliedKey();
  backgroundDismissed=backgroundPaused;areas.mode=null;
  render(true);if(tool==='crop')newCrop();
}
$('undo').onclick=()=>navigateHistory(-1);$('redo').onclick=()=>navigateHistory(1);
$('reset').onclick=()=>{flushAdjustment();ask('Reset semua perubahan?','Foto dikembalikan ke original. Reset tetap dapat di-undo.','Reset',async()=>{if(before)setBefore(false);editState=freshState();resetBackgroundRound();commit();await render(true);if(tool==='crop')newCrop();await enterBackground()})};
$('fit').onclick=fit;$('center').onclick=()=>{pan={x:0,y:0};updateView()};$('zoom-value').onclick=()=>setZoom(1);
$('zoom-in').onclick=()=>setZoom(zoom*1.25);$('zoom-out').onclick=()=>setZoom(zoom/1.25);
viewport.addEventListener('wheel',e=>{if(!originalImage)return;e.preventDefault();const r=viewport.getBoundingClientRect();setZoom(zoom*Math.exp(-e.deltaY*.0015),{x:e.clientX-r.left-r.width/2,y:e.clientY-r.top-r.height/2})},{passive:false});
new ResizeObserver(()=>{if(fitted)fit();else updateView()}).observe(viewport);
function imagePoint(e){const rect=stage.getBoundingClientRect();return {x:(e.clientX-rect.left)/zoom,y:(e.clientY-rect.top)/zoom}}
viewport.addEventListener('pointerdown',e=>{
  if(!originalImage||e.button!==0||exporting||before||aiBusy)return;
  if(e.target.closest('button')&&!e.target.dataset.handle)return;
  if(['adjust','background'].includes(tool)&&!spacePan&&areas.pointerDown(e,imagePoint(e))){viewport.setPointerCapture(e.pointerId);e.preventDefault();return}
  if(tool==='retouch'&&retouch.pointerDown(e,imagePoint(e))){viewport.setPointerCapture(e.pointerId);e.preventDefault();return}
  if(tool==='ai'&&!spacePan&&aiEdit.pointerDown(e,imagePoint(e))){viewport.setPointerCapture(e.pointerId);e.preventDefault();return}
  if(tool==='crop'&&crop){
    const point=imagePoint(e);const inBox=e.target.closest('#crop-box');
    if(!inBox)return;
    gesture={kind:e.target.dataset.handle?'resize':'move',handle:e.target.dataset.handle,point,rect:{...crop},id:e.pointerId};
  }else{gesture={kind:'pan',x:e.clientX,y:e.clientY,pan:{...pan},id:e.pointerId};viewport.classList.add('panning');fitted=false}
  viewport.setPointerCapture(e.pointerId);e.preventDefault();
});
viewport.addEventListener('pointermove',e=>{
  if(['adjust','background'].includes(tool)&&areas.pointerMove(imagePoint(e)))return;
  if(tool==='retouch'&&retouch.pointerMove(imagePoint(e)))return;
  if(tool==='ai'&&aiEdit.pointerMove(imagePoint(e)))return;
  if(!gesture||gesture.id!==e.pointerId)return;
  if(gesture.kind==='pan'){pan={x:gesture.pan.x+e.clientX-gesture.x,y:gesture.pan.y+e.clientY-gesture.y};updateView();return}
  const point=imagePoint(e),dx=point.x-gesture.point.x,dy=point.y-gesture.point.y;
  crop=gesture.kind==='move'?moveCrop(gesture.rect,dx,dy,currentPreview.width,currentPreview.height):resizeCrop(gesture.rect,gesture.handle,dx,dy,currentPreview.width,currentPreview.height,ratio());
  updateCrop();
});
function endGesture(){areas.pointerUp();retouch?.pointerEnd();aiEdit?.pointerEnd();gesture=null;viewport.classList.remove('panning')}
viewport.addEventListener('pointerup',endGesture);viewport.addEventListener('pointercancel',endGesture);viewport.addEventListener('lostpointercapture',endGesture);

function setBefore(value){
  if(!originalImage||before===value)return;
  if(value){flushAdjustment();beforeView={zoom,pan:{...pan},fitted};before=true;showPixels();fit()}
  else{before=false;showPixels();if(beforeView){({zoom,pan,fitted}=beforeView);beforeView=null}updateView()}
  $('before-label').hidden=!before;$('before').classList.toggle('active',before);$('image-stage').classList.toggle('showing-original',before);sync();
}
$('before').addEventListener('pointerdown',e=>{if(!originalImage)return;e.preventDefault();$('before').setPointerCapture(e.pointerId);setBefore(true)});
for(const event of ['pointerup','pointercancel','lostpointercapture'])$('before').addEventListener(event,()=>setBefore(false));
$('before').addEventListener('keydown',e=>{if([' ','Enter'].includes(e.key)){e.preventDefault();setBefore(true)}});
$('before').addEventListener('keyup',e=>{if([' ','Enter'].includes(e.key)){e.preventDefault();setBefore(false)}});
$('before').addEventListener('blur',()=>setBefore(false));window.addEventListener('blur',()=>{spacePan=false;setBefore(false);endGesture()});
document.addEventListener('keydown',e=>{
  if($('export-dialog').open||$('confirm-dialog').open||['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName))return;
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();navigateHistory(e.shiftKey?1:-1)}
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='y'){e.preventDefault();navigateHistory(1)}
  if(e.code==='Space'&&!e.repeat&&e.target.tagName!=='BUTTON'){e.preventDefault();if(tool==='ai'||(['adjust','background'].includes(tool)&&areas.mode)){spacePan=true;return}setBefore(true)}
});
document.addEventListener('keyup',e=>{if(e.code==='Space'){spacePan=false;setBefore(false)}});
function exportOptions(){
  if(!originalImage)return;
  const reduced=editState.operations.some(op=>op.type==='resize'&&op.reason==='performance');
  $('export-size').querySelector('[value=original]').textContent=reduced?'Awal kerja · setelah pengurangan resolusi':'Original · sisi terpanjang foto asli';
  const base=workingOriginalSize(originalImage.naturalWidth,originalImage.naturalHeight,editState.operations);
  const size=exportSize(currentPreview.width,currentPreview.height,base.width,base.height,$('export-size').value);
  $('export-dimensions').textContent=`${size.width} × ${size.height} px · aspect ratio hasil edit dipertahankan`;
  $('quality-field').hidden=$('export-format').value==='image/png';$('quality-value').textContent=$('export-quality').value+'%';
  $('export-note').textContent=$('export-format').value==='image/jpeg'?'JPEG menggunakan latar putih untuk area transparan.':'Transparansi foto dipertahankan.';
}
$('export').onclick=async()=>{retouch?.cancel();aiEdit?.cancel();flushAdjustment();await render();if(before)setBefore(false);if(editState.operations.some(op=>op.type==='resize'&&op.reason==='performance'))$('export-size').value='current';exportOptions();$('export-dialog').showModal()};
$('export-format').onchange=exportOptions;$('export-size').onchange=exportOptions;$('export-quality').oninput=exportOptions;
$('export-cancel').onclick=()=>$('export-dialog').close();
$('export-form').onsubmit=async e=>{
  e.preventDefault();if(exporting||!originalImage)return;
  exporting=true;$('export-submit').disabled=true;sync();let url;
  try{
    const saved=signature(editState),type=$('export-format').value;
    const base=workingOriginalSize(originalImage.naturalWidth,originalImage.naturalHeight,editState.operations);
  const size=exportSize(currentPreview.width,currentPreview.height,base.width,base.height,$('export-size').value);
    const blob=await encodeExport(currentPreview,type,Number($('export-quality').value)/100,size);
    const extension={'image/jpeg':'.jpg','image/png':'.png','image/webp':'.webp'}[type];
    const name=$('export-name').value.trim().replace(/\.(jpe?g|png|webp)$/i,'').replace(/[<>:"/\\|?*\x00-\x1f]/g,'-').replace(/[. ]+$/g,'')||'foto-edited';
    const historySaved=await saveWorkspace();
    const link=document.createElement('a');url=URL.createObjectURL(blob);link.href=url;link.download=name+extension;
    document.body.append(link);link.click();link.remove();exportedSignature=saved;
    $('export-dialog').close();notice('Salinan '+name+extension+' siap diunduh.'+(historySaved?' Hasil tersimpan di Riwayat.':' Riwayat belum tersimpan; tekan Simpan untuk mencoba lagi.'),!historySaved);
    if(lastExportUrl)URL.revokeObjectURL(lastExportUrl);
    lastExportUrl=url;url=null;
    $('export-download').href=lastExportUrl;$('export-download').download=name+extension;$('export-download').hidden=false;
  }catch(error){notice('Export gagal. '+error.message,true);$('export-dialog').close()}
  finally{if(url)setTimeout(()=>URL.revokeObjectURL(url),60_000);exporting=false;$('export-submit').disabled=false;sync()}
};
window.addEventListener('beforeunload',e=>{if(dirty()||aiBusy||historySaving){e.preventDefault();e.returnValue=''}});
retouch=new AIRetouchController({
  hasAppliedRetouch:()=>editState.operations.some(op=>op.type==='retouch'&&op.origin!=='ai-edit'),
  appliedRetouchKey:()=>JSON.stringify(editState.operations.filter(op=>op.type==='retouch'&&op.origin!=='ai-edit').map(op=>op.id)),
  focusFace:bbox=>{if(!bbox||!originalImage)return;const [x0,y0,x1,y1]=bbox;zoom=clamp(Math.min(viewport.clientWidth/Math.max(1,x1-x0),viewport.clientHeight/Math.max(1,y1-y0))*.7,.001,8);pan={x:(preview.width/2-(x0+x1)/2)*zoom,y:(preview.height/2-(y0+y1)/2)*zoom};fitted=false;updateView()},
  hasImage:()=>!!originalImage&&!resolutionPending,signature:()=>signature(editState),flush:flushAdjustment,
  source:async()=>{await render();return currentPreview},size:()=>({width:currentPreview?.width||1,height:currentPreview?.height||1}),zoom:()=>zoom,
  lock:value=>{aiBusy=value;sync()},notice,
  restore:()=>{if(originalImage&&currentPreview){showPixels();updateView()}},
  preview:image=>{captureComparison();if(before)setBefore(false);showPixels();updateView()},
  apply:async(result,settings)=>{captureComparison();editState.operations.push({type:'retouch',id:result.id,width:result.width,height:result.height,settings});editState.adjust=freshState().adjust;delete editState.area;delete editState.background;areas.target='all';areas.status='';editState.filter='none';editState.filterIntensity=100;commit();comparisonCommittedKey=signature(editState);await render();await saveWorkspace();}
});
aiEdit=new AIEditController({
  hasImage:()=>!!originalImage&&!resolutionPending,signature:()=>signature(editState),flush:flushAdjustment,
  source:async()=>{await render();return currentPreview},size:()=>({width:currentPreview?.width||1,height:currentPreview?.height||1}),zoom:()=>zoom,
  lock:value=>{aiBusy=value;sync()},notice,refresh:sync,
  restore:()=>{if(originalImage&&currentPreview){showPixels();updateView()}},
  preview:image=>{if(before)setBefore(false);preview.width=currentPreview.width;preview.height=currentPreview.height;preview.getContext('2d').drawImage(image,0,0);updateView()},
  apply:async(result,settings,image)=>{
    if(editState.operations.length>=500)throw Error('Batas 500 operasi tercapai. Export lalu buka hasil sebagai foto baru.');
    retouch.snapshots.register(result,image);
    editState.operations.push({type:'retouch',id:result.id,width:result.width,height:result.height,settings,origin:'ai-edit'});
    editState.adjust=freshState().adjust;delete editState.area;delete editState.background;areas.target='all';areas.status='';editState.filter='none';editState.filterIntensity=100;commit();await render();await saveWorkspace();
  }
});
sync();

async function restoreLibrary(){
  const ticket=new URLSearchParams(location.search).get('edit');if(!ticket)return;
  try{
    const payload=await library.open(ticket);
    const file=new File([payload.blob],payload.name,{type:payload.blob.type||'image/png'});
    await decodeFile(file,{fromHistory:true});library.parent=payload.parent;
    if(payload.project){
      library.id=payload.photo;library.signature=JSON.stringify(payload.project.state);
      for(const record of payload.project.snapshots)retouch.snapshots.records.set(record.id,record);
      editState=structuredClone(payload.project.state);history.reset();history.push(editState);
      geometryKey='';exportedSignature=signature(editState);await render(true);
      const settings=payload.project.settings||{};
      const r=settings.retouch||{};
      const manual=r.manual||r;
      for(const key of ['smooth','restore','strength'])if(manual[key]!==undefined){$('ai-'+key).value=manual[key];$('ai-'+key+'-value').textContent=manual[key]}
      for(const key of ['texture','eyes','hair','identity'])if(r[key]!==undefined)$('ai-'+key).checked=r[key];
      if(r.model)$('ai-model').value=r.model;
      if(r.fidelity!==undefined)$('ai-fidelity').value=r.fidelity*100;
      const a=settings.ai||{};
      if(a.model)$('edit-method').value=a.model;
      for(const [id,key]of [['edit-resolution','resolution'],['edit-prompt','prompt'],['edit-context','context'],['edit-steps','steps'],['edit-seed','seed']])if(a[key]!==undefined)$(id).value=a[key];
      if(a.strength!==undefined)$('edit-strength').value=a.strength*100;if(a.low_memory!==undefined)$('edit-low-memory').checked=a.low_memory;
      retouch.suppressNextAutoPreview=true;if(a.model&&a.resolution)aiEdit.resolutions[a.model]=a.resolution;
      retouch.sync();aiEdit.sync();
      const next=['adjust','filter','crop','background','retouch','ai'].includes(payload.project.tool)?payload.project.tool:'adjust';selectTool(next);
    }
    notice('Foto dibuka dari Riwayat. Hasil lama tetap tersimpan.');offerResolution();if(!resolutionPending)retouch?.photoLoaded();window.history.replaceState(null,'','/retouch');
  }catch(error){notice('Foto Riwayat gagal dibuka. '+error.message,true)}
}
restoreLibrary();
