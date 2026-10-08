import {test} from 'node:test';
import assert from 'node:assert/strict';
import {AIEditController,MASK_POINT_LIMIT} from '../web/retouch/ai-edit-controller.mjs';

function fixture(){
  const elements=new Map(),draws=[];
  globalThis.document={getElementById(id){
    if(!elements.has(id))elements.set(id,{value:'',checked:false,hidden:false,disabled:false,classList:{toggle(){}},setAttribute(){},removeAttribute(){},getContext(){return {beginPath(){},arc(){},fill(){draws.push(this.globalCompositeOperation)}}}});
    return elements.get(id);
  }};
  globalThis.window={addEventListener(){}};
  globalThis.Image=class{async decode(){}};
  for(const [id,value] of Object.entries({'edit-method':'lama','edit-resolution':'512','edit-prompt':'','edit-context':'64','edit-steps':'20','edit-strength':'95','edit-seed':'0','edit-brush-size':'40'}))document.getElementById(id).value=value;
  document.getElementById('edit-show-mask').checked=true;document.getElementById('edit-low-memory').checked=true;
  const calls={preview:0,apply:0,restore:0,refresh:0,locks:[],cancel:[]};
  const controller=new AIEditController({hasImage:()=>true,flush(){},source:async()=>({}),signature:()=>'source',size:()=>({width:200,height:100}),zoom:()=>1,
    lock:v=>calls.locks.push(v),refresh:()=>calls.refresh++,notice(){},preview:()=>calls.preview++,apply:async()=>calls.apply++,restore:()=>calls.restore++});
  controller.service={upload:async()=>({document:'doc',revision:1}),run:async()=>({url:'/result',id:'result'}),cancel:async job=>calls.cancel.push(job)};
  return {controller,calls,elements,draws};
}

test('resolution is remembered per model and changing it discards an obsolete preview',()=>{
  const {controller:c,elements:e,calls}=fixture();assert.equal(c.settings().resolution,512);
  c.temporary=true;e.get('edit-resolution').value='1024';e.get('edit-resolution').onchange();assert.equal(calls.restore,1);assert.equal(c.temporary,false);
  e.get('edit-method').value='sd15';e.get('edit-method').onchange();assert.equal(c.settings().resolution,512);assert.match(e.get('edit-resolution-1024').textContent,/eksperimen/);
  e.get('edit-resolution').value='768';e.get('edit-resolution').onchange();
  e.get('edit-method').value='lama';e.get('edit-method').onchange();assert.equal(c.settings().resolution,1024);
  e.get('edit-method').value='sd15';e.get('edit-method').onchange();assert.equal(c.settings().resolution,768);
});

test('memory failure offers a lower resolution and retries only on explicit click',async()=>{
  const {controller:c,elements:e,calls}=fixture();c.show(true);c.pointerDown({}, {x:100,y:50});c.pointerEnd();
  e.get('edit-resolution').value='1024';e.get('edit-resolution').onchange();let attempts=[];
  c.service.run=async(kind,data)=>{attempts.push({kind,resolution:data.settings.resolution});if(attempts.length===1)throw Object.assign(Error('VRAM penuh'),{code:'memory'});return {url:'/result'}};
  await c.apply();assert.equal(attempts.length,1);assert.equal(calls.apply,0);assert.equal(e.get('edit-retry-resolution').hidden,false);assert.match(e.get('edit-retry-resolution').textContent,/768/);
  await e.get('edit-retry-resolution').onclick();assert.deepEqual(attempts,[{kind:'apply',resolution:1024},{kind:'apply',resolution:768}]);assert.equal(calls.apply,1);
  assert.equal(e.get('edit-retry-resolution').hidden,true);
});

test('eraser works at full paint budget; clear restores both tools and their notification state',()=>{
  const {controller:c,elements:e,draws}=fixture();c.show(true);c.stamp({x:100,y:50});c.drawMask();
  c.paintCount=MASK_POINT_LIMIT;c.stamp({x:120,y:50});assert.equal(c.strokes.length,1);
  e.get('edit-eraser').onclick();c.stamp({x:100,y:50});c.drawMask();
  assert.equal(c.strokes.length,2);assert.equal(c.eraseCount,1);assert.equal(c.strokes[1].erase,true);
  assert.deepEqual(draws,['source-over','destination-out']);
  c.drawMask();assert.equal(draws.length,2,'unchanged stamps must not be replayed');
  e.get('edit-clear-mask').onclick();assert.equal(c.paintCount,0);assert.equal(c.eraseCount,0);assert.equal(c.limitNotice,null);
  e.get('edit-brush').onclick();c.stamp({x:100,y:50});c.drawMask();assert.equal(c.paintCount,1);assert.equal(draws.at(-1),'source-over');
});

test('visibility icon hides the overlay without discarding marks; duplicate stamps are skipped',()=>{
  const {controller:c,elements:e}=fixture();c.show(true);c.stamp({x:100,y:50});c.stamp({x:100,y:50});c.drawMask();
  assert.equal(c.strokes.length,1);assert.equal(e.get('edit-mask-overlay').hidden,false);
  e.get('edit-show-mask').onclick();assert.equal(e.get('edit-mask-overlay').hidden,true);assert.equal(c.strokes.length,1);
  e.get('edit-show-mask').onclick();assert.equal(e.get('edit-mask-overlay').hidden,false);
});

test('large rapid pointer movement includes its endpoint instead of truncating the path',()=>{
  const {controller:c,elements:e}=fixture();c.hooks.size=()=>({width:10000,height:100});e.get('edit-brush-size').value='4';
  c.show(true);c.pointerDown({}, {x:0,y:50});c.pointerMove({x:10000,y:50});c.pointerEnd();
  assert.equal(c.strokes.at(-1).x,1);assert.ok(c.strokes.length<=10001);
  for(let i=1;i<c.strokes.length;i++)assert.ok(c.strokes[i].x-c.strokes[i-1].x<=.000101,'thin fast strokes must remain continuous');
});

test('method switch reveals only SD settings and requires mask plus prompt',()=>{
  const {controller:c,elements:e}=fixture();assert.equal(c.canRun(),false);
  c.show(true);c.pointerDown({}, {x:100,y:50});c.pointerEnd();assert.equal(c.canRun(),true);
  e.get('edit-method').value='sd15';c.sync();assert.equal(e.get('edit-prompt-field').hidden,false);assert.equal(e.get('edit-sd-settings').hidden,false);assert.equal(c.canRun(),false);
  e.get('edit-prompt').value='wooden bench';c.sync();assert.equal(c.canRun(),true);
  e.get('edit-method').value='lama';c.sync();assert.equal(e.get('edit-prompt-field').hidden,true);assert.equal(e.get('edit-sd-settings').hidden,true);
  assert.equal(c.settings().low_memory,true);
});

test('Preview stays separate, Cancel discards it, Apply commits once and clears mask',async()=>{
  const {controller:c,calls}=fixture();c.show(true);c.pointerDown({}, {x:100,y:50});c.pointerEnd();
  await c.run('preview');assert.equal(c.temporary,true);assert.equal(calls.preview,1);assert.equal(calls.apply,0);
  c.cancel();assert.equal(c.temporary,false);assert.equal(c.strokes.length,0);assert.equal(calls.restore,1);
  c.pointerDown({}, {x:100,y:50});c.pointerEnd();await c.apply();assert.equal(calls.apply,1);assert.equal(c.strokes.length,0);
  assert.deepEqual(calls.locks,[true,false,true,false]);
});

test('cancelled preflight cannot start an inference or commit stale output',async()=>{
  const {controller:c,calls}=fixture();let release;let runs=0;
  c.hooks.source=()=>new Promise(resolve=>release=resolve);c.service.run=async()=>{runs++;return {url:'/result'}};
  c.show(true);c.pointerDown({}, {x:100,y:50});c.pointerEnd();
  const pending=c.apply();assert.equal(c.busy,true);c.cancel();release({});await pending;
  assert.equal(runs,0);assert.equal(calls.apply,0);assert.equal(c.busy,false);assert.deepEqual(calls.locks,[true,false]);
});

test('in-flight Cancel requests server cancellation and ignores late successful results',async()=>{
  const {controller:c,calls}=fixture();let finish;
  c.service.run=async(kind,data,progress,onJob)=>{onJob('job-1');return new Promise(resolve=>finish=resolve)};
  c.show(true);c.pointerDown({}, {x:100,y:50});c.pointerEnd();const pending=c.apply();
  while(!finish)await new Promise(resolve=>setTimeout(resolve,0));
  c.cancel();assert.equal(c.busy,true);assert.deepEqual(calls.cancel,['job-1']);finish({url:'/late-result'});await pending;
  assert.equal(calls.apply,0);assert.equal(c.busy,false);
});
