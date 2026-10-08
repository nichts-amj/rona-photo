import {test} from 'node:test';
import assert from 'node:assert/strict';
import {stackFilter,stackAdjust,cancelPendingLook,freshState,EditHistory,renderGeometry,filterString} from '../web/retouch/engine.mjs';

test('Cancel clears only the active pending look and preserves applied layers and Undo',()=>{
  let state=freshState();state.filter='warm';state=stackFilter(state);
  state.adjust.sharpness=30;state.adjust.vignette=-20;state.filter='noir';state.filterIntensity=55;
  const before=structuredClone(state),cancelFilter=cancelPendingLook(state,'filter');
  assert.deepEqual(state,before);assert.deepEqual(cancelFilter.operations,before.operations);
  assert.deepEqual(cancelFilter.adjust,before.adjust);assert.equal(cancelFilter.filter,'none');assert.equal(cancelFilter.filterIntensity,100);
  const cancelAdjust=cancelPendingLook(state,'adjust');
  assert.deepEqual(cancelAdjust.adjust,freshState().adjust);assert.equal(cancelAdjust.filter,'noir');
  assert.deepEqual(cancelAdjust.operations,before.operations);
  const history=new EditHistory();history.push(state);history.push(cancelAdjust);
  assert.deepEqual(history.undo(),before);assert.deepEqual(history.redo(),cancelAdjust);
  assert.equal(cancelPendingLook(freshState(),'adjust'),null);assert.equal(cancelPendingLook(freshState(),'filter'),null);
  assert.equal(cancelPendingLook(state,'retouch'),null);
});

test('Adjust Apply retains advanced settings and the visible filter, and supports further adjustments',()=>{
  const source=freshState();assert.equal(stackAdjust(source),null);
  source.adjust.exposure=.5;source.adjust.vignette=35;source.filter='warm';source.filterIntensity=60;
  const before=structuredClone(source),applied=stackAdjust(source);
  assert.deepEqual(source,before);assert.deepEqual(applied.adjust,freshState().adjust);
  assert.deepEqual(applied.operations[0],{type:'look',adjust:before.adjust,filter:'warm',filterIntensity:60});
  applied.adjust.contrast=10;const twice=stackAdjust(applied);
  assert.equal(twice.operations.length,2);assert.equal(twice.operations[0].adjust.vignette,35);
  assert.equal(twice.operations[1].adjust.contrast,10);
  const history=new EditHistory();history.push(before);history.push(applied);history.push(twice);
  assert.deepEqual(history.undo(),applied);assert.deepEqual(history.redo(),twice);
});

test('Apply preserves the visible recipe, isolates source state and resets pending controls',()=>{
  const source=freshState();source.operations.push({type:'rotate',direction:1});
  source.adjust.brightness=12;source.adjust.sharpness=24;source.filter='cinematic';source.filterIntensity=65;
  const before=structuredClone(source),result=stackFilter(source);
  assert.deepEqual(source,before);
  assert.deepEqual(result.operations[1],{type:'look',adjust:source.adjust,filter:'cinematic',filterIntensity:65});
  assert.deepEqual(result.adjust,freshState().adjust);assert.equal(result.filter,'none');assert.equal(result.filterIntensity,100);
  result.operations[1].adjust.brightness=99;assert.equal(source.adjust.brightness,12);
});

test('successive Apply actions retain ordered layers and Undo/Redo restore pending selections',()=>{
  const history=new EditHistory();let state=freshState();state.filter='warm';history.push(state);
  state=stackFilter(state);history.push(state);state.filter='noir';state.filterIntensity=40;history.push(state);
  const pending=structuredClone(state);state=stackFilter(state);history.push(state);
  assert.deepEqual(state.operations.map(op=>op.filter),['warm','noir']);
  assert.deepEqual(history.undo(),pending);assert.deepEqual(history.redo(),state);
  history.push(freshState());assert.deepEqual(history.undo(),state);
});

test('Original, zero intensity and unrecognised presets do not add layers',()=>{
  const state=freshState();assert.equal(stackFilter(state),null);
  state.filter='warm';state.filterIntensity=0;assert.equal(stackFilter(state),null);
  state.filter='unknown';state.filterIntensity=100;assert.equal(stackFilter(state),null);
  state.filter='warm';delete state.filterIntensity;assert.equal(stackFilter(state).operations[0].filterIntensity,100);
});

test('renderer replays layers in order and skips layers already baked into an AI snapshot',()=>{
  const oldDocument=globalThis.document,draws=[];
  globalThis.document={createElement(){
    const context={filter:'none',drawImage(source){draws.push({source,filter:this.filter})},translate(){},rotate(){},scale(){}};
    return {width:0,height:0,getContext(){return context}};
  }};
  try{
    const original={naturalWidth:20,naturalHeight:10};
    let state=freshState();state.filter='warm';state=stackFilter(state);state.filter='mono';state=stackFilter(state);
    const result=renderGeometry(original,state.operations);
    assert.deepEqual(draws.map(draw=>draw.filter),['none',...state.operations.map(filterString)]);
    assert.equal(result.width,20);assert.equal(result.height,10);assert.equal(original.naturalWidth,20);
    draws.length=0;const snapshot={naturalWidth:8,naturalHeight:6};
    const baked=[state.operations[0],{type:'retouch',id:'ai-1'},state.operations[1]];
    const afterAI=renderGeometry(original,baked,id=>id==='ai-1'?snapshot:null);
    assert.equal(draws[0].source,snapshot);assert.deepEqual(draws.map(draw=>draw.filter),['none',filterString(state.operations[1])]);
    assert.equal(afterAI.width,8);assert.equal(afterAI.height,6);
  }finally{if(oldDocument===undefined)delete globalThis.document;else globalThis.document=oldDocument}
});
