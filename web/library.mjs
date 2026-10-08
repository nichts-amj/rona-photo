const $=id=>document.getElementById(id);
let token='',listing=null,detail=null,editRequest=null,deleteRequest=null;
const galleryCache=window.RonaHistoryCache;
let refreshing=null,cacheSession='';
function loading(active,text='Memuat riwayat…'){
 $('history-loading').hidden=!active;$('history-loading-text').textContent=text;
 $('grid').setAttribute('aria-busy',String(active));$('refresh').disabled=active;
}
const size=n=>n>=1048576?(n/1048576).toFixed(1)+' MB':Math.ceil(n/1024)+' KB';
const date=n=>new Date(n*1000).toLocaleString('id-ID',{dateStyle:'medium',timeStyle:'short'});
const label=m=>m==='retouch'?'Retouch':'Upscale';
const node=(tag,text,cls)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el};
function notice(text,error=false){$('notice-text').textContent=text;$('notice').classList.toggle('error',error);$('notice').hidden=false}
$('notice-close').onclick=()=>$('notice').hidden=true;
async function api(path,data){
 if(data&&!token){const response=await fetch('/api/retouch/status');token=(await response.json()).token}
 const response=await fetch(path,data?{method:'POST',headers:{'X-Studio-Token':token,'Content-Type':'application/json'},body:JSON.stringify(data)}:{});
 const result=await response.json();if(!response.ok)throw Error(result.error?.message||result.error||'Riwayat tidak tersedia.');return result;
}
function button(text,fn,cls){const b=node('button',text,cls);b.type='button';b.onclick=()=>Promise.resolve().then(fn).catch(e=>notice(e.message,true));return b}
function actionIcon(el,label,kind){
 const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 16 16');svg.setAttribute('aria-hidden','true');
 svg.innerHTML=kind==='edit'?'<path d="M12.854.146a.5.5 0 0 0-.708 0L10.5 1.793 14.207 5.5l1.647-1.646a.5.5 0 0 0 0-.708zM13.5 6.207 9.793 2.5 1 11.293V15h3.707zM2 12l2 2H2z"/>':kind==='download'?'<path d="M7.5 1a.5.5 0 0 1 1 0v8.793l2.146-2.147a.5.5 0 0 1 .708.708l-3 3a.5.5 0 0 1-.708 0l-3-3a.5.5 0 0 1 .708-.708L7.5 9.793zM2 11a.5.5 0 0 1 .5.5V14h11v-2.5a.5.5 0 0 1 1 0V14A1 1 0 0 1 13.5 15h-11a1 1 0 0 1-1-1v-2.5A.5.5 0 0 1 2 11"/>':'<use href="/icons.svg#trash"/>';
 el.replaceChildren(svg);el.classList.add('icon-action');el.setAttribute('aria-label',label);el.title=label;return el;
}
function download(url,name){if(!url){return actionIcon(node('span',undefined,'unavailable'),'Unduh tidak tersedia','download')}const a=actionIcon(node('a',undefined,'download'),'Unduh','download');a.href=url;a.download=url.endsWith('.png')?(name||'foto').replace(/\.[^.]+$/,'')+'.png':name||'foto.png';return a}
function image(url,name){
 if(!url)return node('span','Foto tidak tersedia','missing-photo');
 const im=node('img'),cached=galleryCache?.thumbnail(url);im.alt=name;im.loading='lazy';
 let objectUrl=null;
 im.onload=()=>{
  if(objectUrl){URL.revokeObjectURL(objectUrl);objectUrl=null;return}
  try{const canvas=document.createElement('canvas');const scale=Math.min(1,320/im.naturalWidth,256/im.naturalHeight);canvas.width=Math.max(1,Math.round(im.naturalWidth*scale));canvas.height=Math.max(1,Math.round(im.naturalHeight*scale));canvas.getContext('2d').drawImage(im,0,0,canvas.width,canvas.height);galleryCache?.remember(url,canvas.toDataURL('image/webp',.75))}catch{}
 };
 if(cached){
  try{const [header,body]=cached.split(',');const bytes=Uint8Array.from(atob(body),letter=>letter.charCodeAt(0));objectUrl=URL.createObjectURL(new Blob([bytes],{type:header.slice(5).split(';')[0]}))}catch{}
 }
 im.onerror=()=>{if(objectUrl){URL.revokeObjectURL(objectUrl);objectUrl=null;im.src=url}};
 im.src=objectUrl||url;return im;
}
function photoUrl(item,result=null){return result?.url||item.runs.flatMap(run=>run.results).find(result=>result.url)?.url||item.original||item.source||null}
function requestFor(item,run,result){return {module:item.module,id:item.id,...(run?{run:run.id}:{}),...(result?{result:result.file}:{})}}
function openEdit(request,name){editRequest=request;$('edit-name').textContent=name+' · Terakhir diedit di '+label(request.module);$('prepare-note').hidden=true;$('prepare').hidden=true;$('edit-error').hidden=true;$('edit-dialog').showModal()}
async function edit(target,prepare=false){
 for(const id of ['edit-retouch','edit-upscale','prepare'])$(id).disabled=true;
 try{const result=await api('/api/library/edit',{...editRequest,target,prepare});
  if(result.needs_prepare){$('prepare-note').textContent=result.message;$('prepare-note').hidden=false;$('prepare').hidden=false;return}
  location.assign(result.url);
 }catch(e){$('edit-error').textContent=e.message;$('edit-error').hidden=false}
 finally{for(const id of ['edit-retouch','edit-upscale','prepare'])$(id).disabled=false}
}
$('edit-retouch').onclick=()=>edit('retouch');$('edit-upscale').onclick=()=>edit('upscale');$('prepare').onclick=()=>edit('upscale',true);$('edit-close').onclick=()=>$('edit-dialog').close();
async function askDelete(request){
 $('storage-menu').open=false;
 const preview=await api('/api/library/delete',request);deleteRequest={...request,confirm:true,signature:preview.signature};
 $('delete-text').textContent='Sebanyak '+size(preview.bytes)+' berkas akan dibersihkan.';$('delete-error').hidden=true;$('delete-dialog').showModal();
}
$('delete-close').onclick=()=>$('delete-dialog').close();$('delete-confirm').onclick=async()=>{
 $('delete-confirm').disabled=true;
 try{const result=await api('/api/library/delete',deleteRequest);galleryCache?.invalidate();$('delete-dialog').close();notice('Penghapusan selesai. '+size(result.bytes)+' berkas dibersihkan.');await refresh();if(detail)await showDetail(detail.module,detail.id).catch(()=>back())}
 catch(e){$('delete-error').textContent=e.message;$('delete-error').hidden=false}
 finally{$('delete-confirm').disabled=false}
};
function preview(name,before,after){$('preview-name').textContent=name;$('before').src=before;$('after').src=after;$('wipe').value=50;$('before').style.clipPath='inset(0 50% 0 0)';$('preview-dialog').showModal()}
$('wipe').oninput=()=>$('before').style.clipPath=`inset(0 ${100-Number($('wipe').value)}% 0 0)`;$('preview-close').onclick=()=>$('preview-dialog').close();
function card(item,run=null,result=null){
 const c=node('article',undefined,'card');const url=photoUrl(item,result);
 const open=button('',()=>result?preview(item.name,item.original||item.source||url,url):showDetail(item.module,item.id),'card-open');open.append(image(url,item.name),node('h3',result?.label||item.name));c.append(open);
 c.append(node('span',label(item.module),'badge'),node('small',(result?'Dibuat: ':item.result_count?'Terakhir diedit: ':'Diunggah: ')+label(item.module)+' · '+date(run?.created||item.updated)),node('small',size(result?.bytes||item.bytes)));
 const actions=node('div',undefined,'actions');const edit=actionIcon(button('',()=>openEdit(requestFor(item,run,result),item.name)),'Edit','edit');edit.disabled=listing.active;
 const del=actionIcon(button('',()=>askDelete({...requestFor(item,run,result),kind:result?'result':'photo'}),'danger'),'Hapus','trash');del.disabled=listing.active;
 actions.append(edit,del,download(url,item.name));
 if(result){const parameters=node('details',undefined,'parameters');parameters.append(node('summary','Parameter'),node('pre',JSON.stringify(result.config||{},null,2)));c.append(parameters)}
 c.append(actions);
 return c;
}
function renderGrid(){
 const items=listing.items.filter(i=>$('filter').value==='all'||i.module===$('filter').value);
 $('grid').replaceChildren(...items.map(i=>card(i)));$('empty').hidden=items.length>0||!!detail;
}
function displayListing(){
 $('summary').textContent=listing.items.length+' foto · '+listing.result_count+' hasil · '+size(listing.bytes);$('busy').hidden=!listing.active;$('clear-all').disabled=listing.active||!listing.items.length;$('clear-cache').disabled=listing.active||!listing.cache_bytes;renderGrid();
}
async function refresh(useCache=false){
 if(refreshing)return refreshing;
 const provisional=useCache?galleryCache?.peek():null;
 if(provisional&&!listing){listing=provisional;displayListing()}
 loading(!listing);
 refreshing=(async()=>{
  try{
   if(!cacheSession){const session=await api('/api/bootstrap');cacheSession=session.token;token=session.token}
   if(provisional&&!galleryCache?.read(cacheSession)&&!galleryCache?.peek()){
    listing=null;$('grid').replaceChildren();$('summary').textContent='Memuat riwayat…';loading(true);
   }
   const fresh=await api('/api/library/list');
   const changed=JSON.stringify(listing)!==JSON.stringify(fresh);
   galleryCache?.save(fresh,cacheSession);listing=fresh;
   if(changed)displayListing();
  }finally{loading(false);refreshing=null}
 })();return refreshing;
}
$('filter').onchange=()=>{if(listing)renderGrid()};$('refresh').onclick=()=>{galleryCache?.invalidate();refresh().catch(e=>notice(e.message,true))};$('clear-all').onclick=()=>askDelete({kind:'all'}).catch(e=>notice(e.message,true));$('clear-cache').onclick=()=>askDelete({kind:'cache'}).catch(e=>notice(e.message,true));
document.addEventListener('click',event=>{if(!$('storage-menu').contains(event.target))$('storage-menu').open=false});
document.addEventListener('keydown',event=>{if(event.key==='Escape')$('storage-menu').open=false});
function back(){detail=null;$('detail').hidden=true;$('grid').hidden=false;renderGrid()}
$('back').onclick=back;
async function showDetail(module,id){
 loading(true,'Memuat foto dan hasil…');
 try{detail=await api('/api/library/item/'+module+'/'+id)}finally{loading(false)}
 $('grid').hidden=true;$('empty').hidden=true;$('detail').hidden=false;$('detail-name').textContent=detail.name;
 $('detail-edit').disabled=listing.active;$('detail-edit').onclick=()=>openEdit(requestFor(detail),detail.name);
 const runs=detail.runs.map(run=>{const wrap=node('section',undefined,'run');const head=node('div',undefined,'run-head');head.append(node('strong',label(module)+' · '+date(run.created)));wrap.append(head);const grid=node('div',undefined,'grid');grid.append(...run.results.map(result=>card(detail,run,result)));wrap.append(grid);return wrap});
 $('results').replaceChildren(...(runs.length?runs:[node('p','Belum ada hasil tersimpan.')]));
 const photo=(title,url)=>{const c=node('article',undefined,'card');c.append(node('h3',title),image(url,title),download(url,detail.name));return c};
 $('photos').replaceChildren(...[photo('Salinan foto unggahan',detail.source||detail.original),photo('Foto untuk pemrosesan',detail.original||detail.source)]);
 $('cache').replaceChildren(...(detail.caches.length?detail.caches.map(record=>{const c=node('article',undefined,'card');c.append(node('h3',record.label),node('small',size(record.bytes)));if(record.url)c.append(image(record.url,record.label),download(record.url));c.append(node('pre',JSON.stringify(record.settings,null,2)));return c}):[node('p',module==='retouch'?'Cache pemindaian wajah bersifat sementara. Snapshot edit disimpan bersama hasil.':'Tidak ada cache model.')]));
 selectTab('results');
}
function selectTab(name){for(const tab of ['results','photos','cache'])$(tab).hidden=tab!==name;document.querySelectorAll('[data-tab]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.tab===name)))}
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>selectTab(b.dataset.tab));
window.addEventListener('rona-history-invalidated',()=>{cacheSession=''});
window.addEventListener('focus',()=>{cacheSession='';refresh(true).catch(e=>notice(e.message,true))});
window.addEventListener('pageshow',event=>{if(event.persisted){cacheSession='';refresh(true).catch(e=>notice(e.message,true))}});
refresh(true).catch(e=>notice(e.message,true));
