// Navigation/import adapter only; the original Upscale processing script is unchanged.
(()=>{
 const invalidate=()=>window.RonaHistoryCache?.invalidate();
 document.getElementById('process')?.addEventListener('click',invalidate);
 const progress=document.getElementById('progress-panel');
 if(progress)new MutationObserver(invalidate).observe(progress,{attributes:true,attributeFilter:['hidden']});
 const photo=document.getElementById('photo');
 if(photo)new MutationObserver(invalidate).observe(photo,{attributes:true,attributeFilter:['src']});
 const historyButton=document.getElementById('nav-history');
 historyButton?.addEventListener('click',event=>{event.stopImmediatePropagation();location.assign('/history')},true);
 if(location.hash==='#history'){location.replace('/history');return}
 const ticket=new URLSearchParams(location.search).get('edit');if(!ticket)return;
 (async()=>{
  try{
   const response=await fetch('/api/library/handoff/'+encodeURIComponent(ticket));const data=await response.json();if(!response.ok)throw Error(data.error);
   const deadline=Date.now()+15000;while(!token&&Date.now()<deadline)await new Promise(resolve=>setTimeout(resolve,50));
   if(!token)throw Error('Studio belum siap. Muat ulang halaman.');
   if(data.target!=='upscale'||!data.upscale)throw Error('Sesi Edit tidak sesuai dengan Upscale.');
   openHistoryEditor(data.upscale);message('Foto dibuka dari Riwayat. Pengaturan siap digunakan.','success');
   window.history.replaceState(null,'','/upscale');
  }catch(error){message(error.message)}
 })();
})();
