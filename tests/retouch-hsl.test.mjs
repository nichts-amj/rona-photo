import test from 'node:test';
import assert from 'node:assert/strict';
import {applyHSL,hslHasChanges,hueWeights} from '../web/retouch/hsl.mjs';
import {freshState,stackAdjust,cancelPendingLook,EditHistory} from '../web/retouch/engine.mjs';
import {areaHasChanges} from '../web/retouch/area-adjust.mjs';
const adjusted=(rgba,hsl)=>{const data=new Uint8ClampedArray(rgba);applyHSL(data,hsl);return [...data]};
test('neutral HSL preserves every byte and only selected hue bands change',()=>{
 const pixels=[255,0,0,128,0,255,0,255,0,0,255,255,100,100,100,255,1,2,3,0];
 assert.deepEqual(adjusted(pixels,{}),pixels);
 const result=adjusted(pixels,{green:{saturation:-100}});
 assert.deepEqual(result.slice(0,4),pixels.slice(0,4));assert.deepEqual(result.slice(4,8),[128,128,128,255]);
 assert.deepEqual(result.slice(8),pixels.slice(8));
});
test('hue, saturation, luminance operate on pixels and preserve alpha',()=>{
 assert.deepEqual(adjusted([255,0,0,90],{red:{hue:120}}),[0,255,0,90]);
 assert.deepEqual(adjusted([0,128,0,90],{green:{luminance:100}}),[255,255,255,90]);
 assert.deepEqual(adjusted([0,128,0,90],{green:{luminance:-100}}),[0,0,0,90]);
 assert.equal(hslHasChanges({orange:{hue:NaN}}),false);
});
test('colour bands blend continuously across boundaries and wrap red',()=>{
 for(const hue of [0,29.99,30,60,120,180,240,270,300,359.99,360])assert.ok(Math.abs(hueWeights(hue).reduce((n,v)=>n+v[1],0)-1)<1e-9);
 assert.deepEqual(hueWeights(360),hueWeights(0));
 const a=adjusted([255,0,1,255],{red:{hue:20}}),b=adjusted([255,1,0,255],{red:{hue:20}});
 assert.ok(a.slice(0,3).every((v,i)=>Math.abs(v-b[i])<=3));
});
test('HSL-only Apply retains global and regional recipes; Cancel, Undo and reset remain compatible',()=>{
 const state=freshState();state.adjust.hsl={red:{hue:15},blue:{luminance:20}};
 state.area={mask:'m',person:{hsl:{red:{saturation:10}}},background:{hsl:{green:{saturation:-80}}}};
 assert.ok(areaHasChanges(state.area));const applied=stackAdjust(state);
 assert.deepEqual(applied.operations[0].adjust.hsl,state.adjust.hsl);assert.deepEqual(applied.operations[0].area,state.area);
 assert.equal(applied.adjust.hsl,undefined);assert.equal(areaHasChanges(applied.area),false);
 const pending=structuredClone(applied);pending.adjust.hsl={cyan:{hue:25}};
 const cancelled=cancelPendingLook(pending,'adjust');assert.deepEqual(cancelled.operations,applied.operations);assert.equal(cancelled.adjust.hsl,undefined);
 const history=new EditHistory();history.push(state);history.push(applied);assert.deepEqual(history.undo(),state);assert.deepEqual(history.redo(),applied);
 assert.equal(stackAdjust(freshState()),null);
});
