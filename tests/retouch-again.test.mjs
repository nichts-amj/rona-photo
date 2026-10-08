import test from 'node:test';
import assert from 'node:assert/strict';
import {AIRetouchController} from '../web/retouch/ai-controller.mjs';

function fixture(applied=true){
  const nodes=new Map();
  globalThis.document={getElementById(id){if(!nodes.has(id))nodes.set(id,{hidden:true,dataset:{},value:0,classList:{toggle(){}}});return nodes.get(id)}};
  globalThis.window={addEventListener(){}};
  let hasApplied=applied,hasImage=true,scans=0;
  const c=new AIRetouchController({hasAppliedRetouch:()=>hasApplied,hasImage:()=>hasImage,signature:()=> 'result',restore(){},flush(){},lock(){},notice(){}});
  c.service.cancel=async()=>({});
  c.analyze=async()=>scans++;
  return {c,nodes,scans:()=>scans,setApplied:value=>hasApplied=value,setImage:value=>hasImage=value};
}
const settle=()=>new Promise(resolve=>setTimeout(resolve,10));

test('applied photo asks before another scan and decline preserves the result',async()=>{
  const {c,nodes,scans}=fixture();
  c.pauseAfterSave();c.resumeAfterSave();c.show(true);c.queueAnalysis();
  await settle();
  assert.equal(nodes.get('retouch-again-notice').hidden,false);
  assert.equal(nodes.get('ai-controls').disabled,true);
  assert.equal(scans(),0);
  nodes.get('retouch-again-decline').onclick();
  c.show(true);await settle();
  assert.equal(nodes.get('retouch-again-notice').hidden,true);
  assert.equal(scans(),0);
  // An explicit click can offer the choice again.
  c.resumeAfterSave();c.show(true);
  assert.equal(nodes.get('retouch-again-notice').hidden,false);
});

test('accept starts one scan and does not ask again during the same round',async()=>{
  const {c,nodes,scans}=fixture();c.show(true);
  nodes.get('retouch-again-accept').onclick();await settle();
  assert.equal(scans(),1);
  assert.equal(c.pausedAfterSave,false);
  assert.equal(nodes.get('retouch-again-notice').hidden,true);
  c.analysis={faces:[{}]};c.sourceSignature='result';c.schedule=()=>{};
  c.show(false);c.resumeAfterSave();c.show(true);
  assert.equal(nodes.get('retouch-again-notice').hidden,true);
  assert.equal(scans(),1);
});

test('leaving hides consent; returning to an applied photo asks without scanning',async()=>{
  const {c,nodes,scans}=fixture();c.show(true);nodes.get('retouch-again-decline').onclick();
  c.show(false);assert.equal(nodes.get('retouch-again-notice').hidden,true);
  c.show(true);await settle();
  assert.equal(nodes.get('retouch-again-notice').hidden,false);assert.equal(scans(),0);
});

test('fresh upload retains first automatic scan; resolution decision precedes repeat consent',async()=>{
  const {c,nodes,scans,setApplied,setImage}=fixture();
  setImage(false);c.show(true);
  assert.equal(nodes.get('retouch-again-notice').hidden,true);
  setImage(true);c.photoLoaded();
  assert.equal(nodes.get('retouch-again-notice').hidden,false);
  await settle();assert.equal(scans(),0);
  c.show(false);await c.resetDocument();setApplied(false);c.show(true);await settle();
  assert.equal(scans(),1);assert.equal(nodes.get('retouch-again-notice').hidden,true);
});

test('successful Apply requires a new decision for the next round',async()=>{
  const {c,nodes}=fixture();c.repeatApproved=true;c.visible=true;c.analysis={faces:[{}]};
  globalThis.Image=class {async decode(){}};
  c.task=async()=>({id:'snapshot',url:'test.png',width:16,height:16});
  c.snapshots.register=()=>{};c.hooks.apply=async()=>{};
  await c.apply();c.resumeAfterSave();c.show(true);
  assert.equal(c.repeatApproved,false);assert.equal(c.pausedAfterSave,true);
  assert.equal(nodes.get('retouch-again-notice').hidden,false);
});

test('approval belongs to the current applied result, not a different history result',()=>{
  const {c,nodes}=fixture();let key='snapshot-1';c.hooks.appliedRetouchKey=()=>key;
  c.show(true);nodes.get('retouch-again-accept').onclick();clearTimeout(c.analysisTimer);
  assert.equal(c.needsRepeatConsent(),false);
  key='snapshot-2';c.show(true);
  assert.equal(c.needsRepeatConsent(),true);assert.equal(nodes.get('retouch-again-notice').hidden,false);
  assert.equal(nodes.get('ai-controls').disabled,true);
});
