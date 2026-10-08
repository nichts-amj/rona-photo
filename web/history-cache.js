// Temporary gallery presentation cache, separate from source photos/model caches.
(()=>{
 const key='rona-history-grid-v1',revisionKey='rona-history-grid-revision';
 let cached=null,timer=null;
 const revision=()=>{try{return localStorage.getItem(revisionKey)||''}catch{return ''}};
 function invalidate(reset=false){
  clearTimeout(timer);
  if(reset){cached=null;try{sessionStorage.removeItem(key)}catch{}}
  else if(cached)cached.revision=null;
  try{localStorage.setItem(revisionKey,Date.now()+':'+Math.random())}catch{}
  window.dispatchEvent(new Event('rona-history-invalidated'));
 }
 function persist(){
  if(!cached||cached.revision!==revision())return;
  try{sessionStorage.setItem(key,JSON.stringify(cached))}catch{}
 }
 function read(session,preview=false){
  try{
   const data=cached||JSON.parse(sessionStorage.getItem(key)||'null');
   if(!Array.isArray(data?.listing?.items)||data.listing.active)return null;
   if(!preview&&data.session!==session){cached=null;sessionStorage.removeItem(key);return null}
   if(!preview&&data.revision!==revision())return null;
   cached=data;return data.listing;
  }catch{return null}
 }
 function save(listing,session){
  cached={session,revision:revision(),listing,thumbnails:cached?.thumbnails||{}};
  persist();
 }
 function thumbnail(url){return cached?.thumbnails?.[url]||null}
 function remember(url,data){
  if(!cached||cached.revision!==revision()||!data.startsWith('data:image/'))return;
  const total=Object.values(cached.thumbnails).reduce((sum,value)=>sum+value.length,0);
  if(total+data.length>2*1024*1024)return;
  cached.thumbnails[url]=data;clearTimeout(timer);timer=setTimeout(persist,150);
 }
 window.RonaHistoryCache={read,peek:()=>read(undefined,true),save,thumbnail,remember,invalidate};
 window.addEventListener('pagehide',persist);
 window.addEventListener('storage',event=>{
  if(event.key===revisionKey)window.dispatchEvent(new Event('rona-history-invalidated'));
 });
 // A browser refresh is an explicit reset; normal module navigation retains it.
 if(performance.getEntriesByType('navigation')[0]?.type==='reload')invalidate(true);
})();
