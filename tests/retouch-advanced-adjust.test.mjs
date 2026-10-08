import test from 'node:test';
import assert from 'node:assert/strict';
import {applyAdvancedAdjust} from '../web/retouch/advanced-adjust.mjs';
import {freshState,EditHistory,drawPreview} from '../web/retouch/engine.mjs';
const change=(pixels,settings)=>{const out=new Uint8ClampedArray(pixels);applyAdvancedAdjust(out,settings);return [...out]};
test('neutral and legacy adjustments leave all source bytes identical',()=>{
  const pixels=[140,110,90,175,12,34,56,0];assert.deepEqual(change(pixels,freshState().adjust),pixels);assert.deepEqual(change(pixels,{}),pixels);
});
test('highlights target bright pixels and shadows target dark pixels',()=>{
  const pixels=[30,30,30,255,200,200,200,255];
  const high=change(pixels,{highlights:100}),shadow=change(pixels,{shadows:100});
  assert.ok(high[4]-200>high[0]-30);assert.ok(shadow[0]-30>shadow[4]-200);
  assert.ok(change(pixels,{highlights:-100})[4]<200);assert.ok(change(pixels,{shadows:-100})[0]<30);
});
test('temperature and tint move in the labeled color directions without changing alpha',()=>{
  const pixels=[100,100,100,175,25,50,75,0];
  const warm=change(pixels,{temperature:100}),cool=change(pixels,{temperature:-100}),magenta=change(pixels,{tint:100}),green=change(pixels,{tint:-100});
  assert.ok(warm[0]>warm[2]);assert.ok(cool[2]>cool[0]);assert.ok(magenta[0]>magenta[1]);assert.ok(green[1]>green[0]);
  for(const result of [warm,cool,magenta,green]){assert.equal(result[3],175);assert.deepEqual(result.slice(4),pixels.slice(4))}
});
test('vibrance preserves neutral grays and can strengthen or soften color',()=>{
  const pixels=[180,120,100,255,100,100,100,128];const up=change(pixels,{vibrance:100}),down=change(pixels,{vibrance:-100});
  assert.ok(up[0]-up[2]>80);assert.ok(down[0]-down[2]<80);assert.deepEqual(up.slice(4),pixels.slice(4));assert.deepEqual(down.slice(4),pixels.slice(4));
});
test('advanced settings participate in Undo/Redo and neutral reset',()=>{
  const h=new EditHistory(),state=freshState();state.adjust.temperature=40;state.adjust.shadows=30;h.push(state);state.adjust.vibrance=25;h.push(state);
  assert.equal(h.undo().adjust.vibrance,0);assert.equal(h.current.adjust.temperature,40);assert.equal(h.redo().adjust.vibrance,25);h.push(freshState());assert.equal(h.undo().adjust.shadows,30);
});
test('filter is applied after advanced color adjustments using copy to preserve transparency',()=>{
  const events=[],context={filter:'none',globalCompositeOperation:'source-over',drawImage(image){events.push({filter:this.filter,composite:this.globalCompositeOperation,self:image===target})},getImageData(){return {data:new Uint8ClampedArray([100,90,80,175])}},putImageData(){events.push({pixels:true})}},target={width:0,height:0,getContext:()=>context};
  const state=freshState();state.adjust.temperature=20;state.filter='mono';drawPreview({width:1,height:1},state,target);
  assert.equal(events[0].filter.includes('grayscale'),false);assert.equal(events[1].pixels,true);assert.equal(events[2].filter,'grayscale(1)');assert.equal(events[2].composite,'copy');assert.equal(events[2].self,true);assert.equal(context.globalCompositeOperation,'source-over');
});
