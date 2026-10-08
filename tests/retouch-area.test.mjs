import test from 'node:test';
import assert from 'node:assert/strict';
import {areaHasChanges,neutralAreas,maskOperations,AreaAdjust} from '../web/retouch/area-adjust.mjs';
import {freshState,stackAdjust,stackFilter,cancelPendingLook,EditHistory} from '../web/retouch/engine.mjs';

test('regional Apply retains both recipes and mask while neutralising sliders',()=>{
  const state=freshState();state.areaMasks={m:{png:'mask',anchor:0,width:10,height:10}};
  state.area={mask:'m',person:{exposure:1},background:{brightness:-20}};
  assert.ok(areaHasChanges(state.area));const next=stackAdjust(state);
  assert.deepEqual(next.operations[0].area,state.area);assert.deepEqual(next.areaMasks,state.areaMasks);
  assert.equal(next.area.mask,'m');assert.equal(areaHasChanges(next.area),false);
  assert.equal(state.area.person.exposure,1);
  next.filter='warm';next.area.person.contrast=15;
  assert.equal(stackFilter(next).operations.at(-1).area.person.contrast,15);
});
test('Cancel clears pending regional edits and preserves applied masks, Undo and Redo',()=>{
  const state=freshState();state.area={mask:'a',person:{exposure:.5},background:{}};state.areaMasks={a:{png:'original'}};
  const applied=stackAdjust(state),pending=structuredClone(applied);pending.area.background.exposure=-1;
  const cancelled=cancelPendingLook(pending,'adjust');assert.deepEqual(cancelled.operations,applied.operations);
  assert.equal(areaHasChanges(cancelled.area),false);assert.equal(cancelled.area.mask,'a');
  const h=new EditHistory();h.push(pending);h.push(cancelled);assert.deepEqual(h.undo(),pending);assert.deepEqual(h.redo(),cancelled);
  neutralAreas(state);assert.equal(areaHasChanges(state.area),false);
});
test('area values are independent and cache identity ignores colour adjustments',()=>{
  const controller=new AreaAdjust({});const state=freshState();state.area={mask:'a',person:{},background:{}};
  controller.target='person';controller.current(state).brightness=20;
  controller.target='background';controller.current(state).brightness=-10;
  controller.target='all';assert.equal(controller.current(state).brightness,0);
  assert.equal(state.area.person.brightness,20);assert.equal(state.area.background.brightness,-10);
  assert.deepEqual(maskOperations([{type:'look'},{type:'crop',x:1},{type:'rotate',direction:1}]),[{type:'crop',x:1},{type:'rotate',direction:1}]);
});
