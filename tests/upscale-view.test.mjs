import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
function fixture(){
 const nodes=new Map();
 for(const id of ['mode','single-model','second-mode','second-single-model','comparison-handle','wipe','result-stage','result-viewport','result-base','result-top'])nodes.set(id,{value:'50',style:{},attrs:{},events:{},addEventListener(k,f){this.events[k]=f},setAttribute(k,v){this.attrs[k]=v},dispatchEvent(e){this.events[e.type]?.(e)},setPointerCapture(){},hasPointerCapture(){return true},releasePointerCapture(){}});
 nodes.get('result-stage').getBoundingClientRect=()=>({left:100,top:100,width:400,height:900,bottom:1000});
 nodes.get('result-viewport').getBoundingClientRect=()=>({top:200,bottom:600});
 vm.runInNewContext(fs.readFileSync(new URL('../web/upscale-view.js',import.meta.url),'utf8'),{document:{getElementById:id=>nodes.get(id)},ResizeObserver:class{observe(){}},Event:class{constructor(type){this.type=type}}});
 return nodes;
}
test('entering Standard selects Real-ESRGAN in both configurations, custom selection remains intact',()=>{
 const nodes=fixture();for(const prefix of ['', 'second-']){const mode=nodes.get(prefix+'mode'),model=nodes.get(prefix+'single-model');mode.value='single';model.value='A';mode.events.change();assert.equal(model.value,'B');mode.value='custom';model.value='H';mode.events.change();assert.equal(model.value,'H')}
});
test('comparison handle tracks visible center and supports bounded pointer/keyboard input',()=>{
 const nodes=fixture(),handle=nodes.get('comparison-handle'),range=nodes.get('wipe');assert.equal(handle.style.top,'300px');
 const e={button:0,pointerId:1,clientX:300,preventDefault(){},stopPropagation(){this.stopped=true}};handle.events.pointerdown(e);assert(e.stopped);assert.equal(Number(range.value),50);
 handle.events.pointermove({...e,clientX:900});assert.equal(Number(range.value),100);handle.events.pointerup(e);
 handle.events.keydown({key:'Home',preventDefault(){}});assert.equal(Number(range.value),0);handle.events.keydown({key:'ArrowRight',shiftKey:true,preventDefault(){}});assert.equal(Number(range.value),10);assert.equal(Number(handle.attrs['aria-valuenow']),10);
});
