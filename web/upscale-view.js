// Presentation controls only; retain Studio inference and result rendering.
(()=>{
 for(const prefix of ['', 'second-']){
  const mode=document.getElementById(prefix+'mode'),model=document.getElementById(prefix+'single-model');
  mode?.addEventListener('change',()=>{if(mode.value==='single')model.value='B'},true);
 }
 const handle=document.getElementById('comparison-handle'),range=document.getElementById('wipe');
 const stage=document.getElementById('result-stage'),viewport=document.getElementById('result-viewport');
 if(!handle||!range||!stage||!viewport)return;
 let pointer=null;
 function position(){
  const s=stage.getBoundingClientRect(),v=viewport.getBoundingClientRect();
  if(!s.height)return;
  const top=Math.max(s.top,v.top),bottom=Math.min(s.bottom,v.bottom);
  const center=bottom>top?(top+bottom)/2:s.top+s.height/2;
  handle.style.top=Math.max(0,Math.min(s.height,center-s.top))+'px';
  handle.setAttribute('aria-valuenow',range.value);
 }
 function setValue(value){range.value=Math.max(0,Math.min(100,value));range.dispatchEvent(new Event('input',{bubbles:true}));position()}
 function move(event){const rect=stage.getBoundingClientRect();if(rect.width)setValue((event.clientX-rect.left)/rect.width*100)}
 handle.addEventListener('pointerdown',event=>{
  if(event.button!==0)return;event.preventDefault();event.stopPropagation();pointer=event.pointerId;handle.setPointerCapture(pointer);move(event);
 });
 handle.addEventListener('pointermove',event=>{if(event.pointerId===pointer){event.preventDefault();event.stopPropagation();move(event)}});
 function end(event){if(event.pointerId===pointer){event.stopPropagation();pointer=null;if(handle.hasPointerCapture(event.pointerId))handle.releasePointerCapture(event.pointerId)}}
 handle.addEventListener('pointerup',end);handle.addEventListener('pointercancel',end);
 handle.addEventListener('keydown',event=>{
  const step=event.shiftKey?10:1;
  const next={ArrowLeft:Number(range.value)-step,ArrowRight:Number(range.value)+step,Home:0,End:100}[event.key];
  if(next!==undefined){event.preventDefault();setValue(next)}
 });
 range.addEventListener('input',position);viewport.addEventListener('scroll',position,{passive:true});
 new ResizeObserver(position).observe(stage);new ResizeObserver(position).observe(viewport);
 for(const id of ['result-base','result-top'])document.getElementById(id)?.addEventListener('load',position);
 position();
})();
