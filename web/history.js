'use strict';
// DOM text is always assigned as textContent; filenames/parameters are never HTML.
(()=>{
 let listing=null,detail=null,pending=null,loading=0;
 const el=(tag,text,className)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(className)n.className=className;return n};
 const size=bytes=>bytes>=1073741824?(bytes/1073741824).toFixed(2)+' GB':bytes>=1048576?(bytes/1048576).toFixed(1)+' MB':Math.ceil(bytes/1024)+' KB';
 const date=value=>new Date(value*1000).toLocaleString('id-ID',{dateStyle:'medium',timeStyle:'short'});
 const action=(text,fn,danger=false)=>{const b=el('button',text,danger?'danger':'');b.type='button';b.onclick=()=>Promise.resolve().then(fn).catch(e=>message(e.message));return b};
 const link=(text,url,className)=>{const a=el('a',text,className);a.href=url;a.download='';return a};
 const image=(url,name)=>{const im=el('img');im.src=url;im.alt=name;im.loading='lazy';return im};
 function page(history){$('studio-view').hidden=history;$('history-view').hidden=!history;for(const [id,active] of [['nav-history',history],['nav-studio',!history]]){$(id).classList.toggle('active',active);if(active)$(id).setAttribute('aria-current','page');else $(id).removeAttribute('aria-current')}}
 $('nav-studio').onclick=()=>page(false);
 $('nav-history').onclick=()=>{page(true);refresh().catch(e=>message(e.message))};
 $('history-refresh').onclick=()=>refresh().catch(e=>message(e.message));
 function locked(){return busy||listing?.active}
 function lockButton(button){button.disabled=!!locked();return button}
 async function refresh(){
  const seq=++loading;const response=await api('/api/history');if(seq!==loading)return;listing=response;
  $('history-summary').textContent=response.items.length+' unggahan · '+response.result_count+' hasil · '+size(response.bytes)+' digunakan';
  $('history-lock').hidden=!response.active;$('history-clear-cache').disabled=response.active||!response.cache_bytes;$('history-clear-all').disabled=response.active||!response.items.length;
  $('history-list').replaceChildren();$('history-empty').hidden=!!response.items.length;
  for(const item of response.items){
   const card=el('article',undefined,'history-card');const open=action('',()=>showDetail(item.id));open.className='history-card-open';
   if(item.original)open.append(image(item.original,item.name));else open.append(el('span','Foto tidak tersedia','history-no-image'));
   open.append(el('h3',item.name),el('small',date(item.created)+' · '+item.result_count+' hasil · '+size(item.bytes)));card.append(open);
   const buttons=el('div',undefined,'history-actions');const edit=lockButton(action('Edit di Studio',()=>editPhoto(item.id)));edit.disabled=edit.disabled||!item.editable;
   const downloads=el('div',undefined,'history-grid-downloads');downloads.hidden=true;
   const download=action('Unduh',async()=>{
    if(!downloads.hidden){downloads.hidden=true;download.setAttribute('aria-expanded','false');return}
    download.disabled=true;
    try{
     const saved=await api('/api/history/'+item.id);
     const results=saved.runs.flatMap(run=>run.results.map(result=>({label:result.label+' · '+date(run.created),url:result.url})));
     if(!results.length&&(saved.source||saved.original))results.push({label:'Foto unggahan',url:saved.source||saved.original});
     if(!results.length)throw Error('Tidak ada berkas yang dapat diunduh.');
     downloads.replaceChildren(el('small','Pilih berkas untuk diunduh'),...results.map(result=>link(result.label,result.url)));
     if(results.length===1){const a=downloads.querySelector('a');a.click();return}
     downloads.hidden=false;download.setAttribute('aria-expanded','true');
    }finally{download.disabled=false}
   });
   download.className='history-download';download.setAttribute('aria-expanded','false');
   buttons.append(edit,download,lockButton(action('Hapus',()=>askDelete({kind:'upload',upload:item.id},'Hapus unggahan “'+item.name+'”, semua hasil, dan cache terkait?'),true)));card.append(buttons,downloads);$('history-list').append(card);
  }
  if(detail){if(response.items.some(i=>i.id===detail.id))await showDetail(detail.id,false);else closeDetail()}
 }
 function tab(name){for(const n of ['results','photos','cache']){$('history-'+n).hidden=n!==name;$('history-tab-'+n).setAttribute('aria-selected',String(n===name));$('history-tab-'+n).tabIndex=n===name?0:-1}}
 const tabs=[...document.querySelectorAll('[data-history-tab]')];tabs.forEach((b,i)=>{b.onclick=()=>tab(b.dataset.historyTab);b.onkeydown=e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const j=e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[j].focus();tab(tabs[j].dataset.historyTab)}}});
 function closeDetail(){detail=null;$('history-detail').hidden=true;$('history-list').hidden=false;$('history-empty').hidden=!!listing?.items.length}
 $('history-back').onclick=closeDetail;
 async function showDetail(uid,resetTab=true){
  const data=await api('/api/history/'+uid);detail=data;$('history-detail').hidden=false;$('history-list').hidden=true;$('history-empty').hidden=true;
  $('history-photo-name').textContent=data.name+' · '+size(data.bytes);$('history-edit').disabled=locked()||!data.editable;
  renderPhotos();renderRuns();renderCaches();if(resetTab)tab('results');
 }
 async function editPhoto(uid,run,result){
  const data=await api('/api/history/edit',{upload:uid,run,result});openHistoryEditor(data);page(false);$('studio-view').scrollIntoView({behavior:'smooth',block:'start'});
 }
 $('history-edit').onclick=()=>editPhoto(detail.id).catch(e=>message(e.message));
 function photoCard(title,url){const card=el('article',undefined,'history-card');card.append(el('h3',title));if(url){const b=action('',()=>preview(title,url));b.className='history-card-open';b.append(image(url,title));card.append(b,link('Unduh foto',url))}else card.append(el('p','Berkas tidak tersedia.'));return card}
 function renderPhotos(){const box=$('history-photos');box.className='history-grid';box.replaceChildren(photoCard('Salinan unggahan',detail.source),photoCard('Foto untuk pemrosesan',detail.original))}
 function parameters(config){const details=el('details',undefined,'history-parameters');details.append(el('summary','Parameter'));const dl=el('dl');
  const labels={device:'Perangkat',tile:'Potongan Swin',output_scale:'Skala keluaran',overlap:'Overlap',b_tile:'Potongan Real-ESRGAN',h_tile:'Potongan HAT',denoise:'Denoise',feather:'Kelembutan batas',fidelity:'Kesetiaan codeFormer',face_mix:'Campuran wajah',reference:'Model area terlindungi',face_model:'Restorasi wajah',use_mask:'Penandaan area',weights:'Kontribusi model'};
  for(const [key,value]of Object.entries(config||{})){if(key==='label')continue;let text=value;if(key==='weights')text=Object.entries(value).filter(([,v])=>v>0).map(([m,v])=>names[m]+': '+Number(v).toFixed(1)).join(' · ');else if(['reference','face_model'].includes(key))text=names[value]||'Nonaktif';else if(typeof value==='boolean')text=value?'Aktif':'Nonaktif';dl.append(el('dt',labels[key]||key),el('dd',String(text)))}details.append(dl);return details;
 }
 function maskPreview(run){const areas=[...(run.known_mask_config?.protected_regions||[]),...(run.regions||[])];const wrap=el('details',undefined,'history-parameters');wrap.append(el('summary','Penandaan tersimpan · '+areas.length+' area'));
  if(!areas.length){wrap.append(el('p','Tidak ada penandaan area pada proses ini.'));return wrap}
  const stage=el('div',undefined,'history-mask');const im=image(detail.original,'Penandaan pada foto sumber');const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('aria-label','Area terlindungi berwarna jingga');
  im.onload=()=>svg.setAttribute('viewBox','0 0 '+im.naturalWidth+' '+im.naturalHeight);
  for(const area of areas){const p=document.createElementNS(svg.namespaceURI,'polygon');const points=area.polygon||(area.box?[[area.box[0],area.box[1]],[area.box[2],area.box[1]],[area.box[2],area.box[3]],[area.box[0],area.box[3]]]:[]);p.setAttribute('points',points.map(a=>a.join(',')).join(' '));svg.append(p)}
  stage.append(im,svg);wrap.append(stage,el('p','Area digunakan pada konfigurasi yang mengaktifkan penandaan.'));return wrap;
 }
 function renderRuns(){const box=$('history-results');box.replaceChildren();if(!detail.runs.length)box.append(el('p','Foto ini belum memiliki hasil. Pilih Edit di Studio untuk memprosesnya.','empty-history'));
  for(const run of detail.runs){const section=el('article',undefined,'history-run');const head=el('div',undefined,'history-run-head');head.append(el('h3',date(run.created)),el('small',size(run.bytes)+' · '+Number(run.seconds).toFixed(1)+' detik'));
   head.append(lockButton(action('Hapus proses',()=>askDelete({kind:'run',upload:detail.id,run:run.id},'Hapus seluruh hasil dan catatan pada proses ini? Cache model dan foto sumber tetap tersimpan.'),true)));section.append(head);
   if(!run.results.length)section.append(el('p',run.error?'Proses gagal: '+run.error:'Proses belum selesai atau tidak menghasilkan berkas.'));
   const grid=el('div',undefined,'history-grid');for(const result of run.results){const card=el('article',undefined,'history-card');const show=action('',()=>preview(result.label,result.url,detail.original));show.className='history-card-open';show.append(image(result.url,result.label),el('h3',result.label),el('small',size(result.bytes)+' · Klik untuk membandingkan'));
    const buttons=el('div',undefined,'history-actions');buttons.append(lockButton(action('Edit',()=>editPhoto(detail.id,run.id,result.file))),link('Unduh',result.url,'history-download'),lockButton(action('Hapus hasil',()=>askDelete({kind:'result',upload:detail.id,run:run.id,result:result.file},'Hapus hasil “'+result.label+'” dan parameter terkait? Foto sumber, hasil lain, dan cache tetap tersimpan.'),true)));
    card.append(show,buttons,parameters(result.config));grid.append(card)}section.append(grid,maskPreview(run));if(run.manifest)section.append(link('Unduh catatan parameter & penandaan',run.manifest));box.append(section);
  }
 }
 function renderCaches(){const box=$('history-cache');box.className='history-grid';box.replaceChildren();if(!detail.caches.length)box.append(el('p','Belum ada cache model. Menghapus cache tidak menghapus hasil akhir.','empty-history'));
  for(const cache of detail.caches){const card=el('article',undefined,'history-card');const show=action('',()=>cache.url&&preview(cache.label,cache.url,detail.original));show.className='history-card-open';if(cache.url)show.append(image(cache.url,cache.label));show.append(el('h3',cache.label),el('small',size(cache.bytes)+' termasuk data pendukung wajah bila ada'));card.append(show,parameters(cache.settings));const buttons=el('div',undefined,'history-actions');if(cache.url)buttons.append(link('Unduh cache',cache.url));buttons.append(lockButton(action('Hapus cache',()=>askDelete({kind:'cache',upload:detail.id,key:cache.key},'Hapus cache '+cache.label+'? Hasil akhir tetap tersimpan; model mungkin perlu dijalankan ulang.'),true)));card.append(buttons);box.append(card)}
 }
 function preview(title,result,original){$('history-preview-title').textContent=title;$('history-preview-base').src=result;$('history-preview-over').hidden=!original;if(original)$('history-preview-over').src=original;$('history-wipe').hidden=!original;$('history-preview-hint').hidden=!original;$('history-wipe').value=50;wipeHistory();$('history-preview').showModal()}
 function wipeHistory(){$('history-preview-over').style.clipPath='inset(0 '+(100-Number($('history-wipe').value))+'% 0 0)'}
 $('history-wipe').oninput=wipeHistory;$('history-preview-close').onclick=()=>$('history-preview').close();
 async function askDelete(request,text){const plan=await api('/api/history/delete',request);pending={...request,signature:plan.signature,confirm:true};$('history-confirm-text').textContent=text+' '+plan.files+' berkas · sekitar '+size(plan.bytes)+' akan dibebaskan.';$('history-delete-error').hidden=true;$('history-delete-confirm').disabled=false;$('history-confirm').showModal()}
 $('history-lock-close').onclick=()=>$('history-lock').hidden=true;
 $('history-delete-error-close').onclick=()=>$('history-delete-error').hidden=true;
 $('history-delete-cancel').onclick=()=>{$('history-confirm').close();pending=null};
 $('history-delete-confirm').onclick=async()=>{if(!pending)return;const request=pending;$('history-delete-confirm').disabled=true;try{const result=await api('/api/history/delete',request);pending=null;$('history-confirm').close();forgetHistoryFiles(request);message('Penghapusan selesai. '+size(result.bytes)+' berkas dibersihkan.','success');await refresh()}catch(e){$('history-delete-error-text').textContent=e.message;$('history-delete-error').hidden=false;$('history-delete-confirm').disabled=false}};
 $('history-clear-cache').onclick=()=>askDelete({kind:'all-cache'},'Bersihkan semua cache model di Riwayat? Foto sumber dan hasil akhir tetap tersimpan.').catch(e=>message(e.message));
 $('history-clear-all').onclick=()=>askDelete({kind:'all'},'Hapus seluruh unggahan, hasil, cache, dan penandaan di Riwayat?').catch(e=>message(e.message));
})();
