import test from 'node:test';
import assert from 'node:assert/strict';
import {applyAdvancedAdjust} from '../web/retouch/advanced-adjust.mjs';
import {applyDetailAdjust} from '../web/retouch/detail-adjust.mjs';
import {freshState,EditHistory} from '../web/retouch/engine.mjs';
test('Whites and Blacks target extreme tones while leaving middle gray and alpha intact',()=>{
  const source=[20,20,20,128,128,128,128,175,220,220,220,255];
  const white=new Uint8ClampedArray(source),black=new Uint8ClampedArray(source);
  applyAdvancedAdjust(white,{whites:50});applyAdvancedAdjust(black,{blacks:50});
  assert.ok(white[8]>220);assert.equal(white[0],20);assert.ok(black[0]>20);assert.equal(black[8],220);
  for(const pixels of [white,black]){assert.equal(pixels[4],128);assert.equal(pixels[3],128);assert.equal(pixels[7],175);assert.equal(pixels[11],255)}
});
test('zero details and sharpening of uniform regions are byte-identical',()=>{
  const source=new Uint8ClampedArray([100,110,120,128,100,110,120,128]);const neutral=source.slice(),sharp=source.slice();
  assert.equal(applyDetailAdjust(neutral,2,1,{}),false);applyDetailAdjust(sharp,2,1,{sharpness:100});assert.deepEqual(neutral,source);assert.deepEqual(sharp,source);
});
test('sharpening increases local detail without reading changed neighbours or transparent colors',()=>{
  const pixels=new Uint8ClampedArray([80,80,80,255,100,100,100,255,120,120,120,255,100,100,100,255,80,80,80,255]);
  applyDetailAdjust(pixels,5,1,{sharpness:100});assert.ok(pixels[8]>120);assert.equal(pixels[0],pixels[16]);assert.equal(pixels[4],pixels[12]);
  const transparent=new Uint8ClampedArray([60,60,60,128,255,255,255,0]),before=transparent.slice();applyDetailAdjust(transparent,2,1,{sharpness:100});assert.deepEqual(transparent,before);
});
test('vignette changes only outer areas in both directions while preserving alpha',()=>{
  const original=new Uint8ClampedArray(5*5*4);for(let i=0;i<original.length;i+=4)original.set([100,100,100,175],i);
  const dark=original.slice(),light=original.slice();applyDetailAdjust(dark,5,5,{vignette:100});applyDetailAdjust(light,5,5,{vignette:-100});
  assert.ok(dark[0]<100);assert.ok(light[0]>100);assert.equal(dark[(2*5+2)*4],100);assert.equal(light[(2*5+2)*4],100);
  for(let i=3;i<original.length;i+=4){assert.equal(dark[i],175);assert.equal(light[i],175)}
});
test('all four controls survive Undo/Redo and reset returns them to neutral',()=>{
  const h=new EditHistory(),s=freshState();Object.assign(s.adjust,{whites:30,blacks:-15,sharpness:20,vignette:35});h.push(s);h.push(freshState());
  const restored=h.undo();for(const key of ['whites','blacks','sharpness','vignette'])assert.equal(restored.adjust[key],s.adjust[key]);
  const neutral=h.redo();for(const key of ['whites','blacks','sharpness','vignette'])assert.equal(neutral.adjust[key],0);
});
