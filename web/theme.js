// Presentation preference only; no photo data or processing settings are changed.
(()=>{
 const key='rona-photo-theme';
 const glassKey='rona-photo-glass';
 let current='day';
 let glass=true;
 try{current=localStorage.getItem(key)==='night'?'night':'day'}catch{}
 try{glass=localStorage.getItem(glassKey)!=='off'}catch{}
 function applyGlass(enabled){
  glass=enabled===true;
  document.documentElement.dataset.glass=glass?'on':'off';
  const button=document.getElementById('glass-toggle');
  if(button){
   button.setAttribute('aria-pressed',String(glass));
   button.setAttribute('aria-label',glass?'Efek kaca aktif. Nonaktifkan efek kaca':'Aktifkan efek kaca untuk Retouch dan Upscale');
   button.title=glass?'Efek kaca aktif · klik untuk menonaktifkan':'Aktifkan efek kaca';
  }
 }
 function apply(theme){
  current=theme==='night'?'night':'day';
  document.documentElement.dataset.theme=current;
  const logo=current==='night'?'/rona-night.svg':'/rona.svg';
  document.querySelectorAll('img[src="/rona.svg"],img[src="/rona-night.svg"]').forEach(image=>{image.src=logo});
  document.querySelectorAll('link[rel="icon"]').forEach(icon=>{icon.href=logo});
  const button=document.getElementById('theme-toggle');
  if(button){
   const night=current==='night';
   button.setAttribute('aria-pressed',String(night));
   button.setAttribute('aria-label',night?'Mode malam aktif. Aktifkan mode siang':'Mode siang aktif. Aktifkan mode malam');
   button.title=night?'Mode malam · klik untuk siang':'Mode siang · klik untuk malam';
  }
 }
 apply(current);
 applyGlass(glass);
 document.addEventListener('DOMContentLoaded',()=>{
  apply(current);
  applyGlass(glass);
  document.getElementById('theme-toggle')?.addEventListener('click',()=>{
   apply(current==='night'?'day':'night');
   try{localStorage.setItem(key,current)}catch{}
  });
  document.getElementById('glass-toggle')?.addEventListener('click',()=>{
   applyGlass(!glass);
   try{localStorage.setItem(glassKey,glass?'on':'off')}catch{}
  });
 });
 window.addEventListener('storage',event=>{
  if(event.key===key)apply(event.newValue);
  if(event.key===glassKey)applyGlass(event.newValue!=='off');
 });
})();
