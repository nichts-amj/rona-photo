import {test} from 'node:test';
import assert from 'node:assert/strict';
import {FILTERS,filterString,EditHistory,freshState,signature,centeredCrop,moveCrop,resizeCrop,integerCrop,exportSize,fitZoom} from '../web/retouch/engine.mjs';

test('undo and redo preserve operations, adjustments and isolated snapshots',()=>{
  const history=new EditHistory();const s=freshState();
  s.operations.push({type:'rotate',direction:1});history.push(s);
  s.operations.push({type:'crop',x:4,y:3,w:12,h:12});history.push(s);
  s.adjust.contrast=10;history.push(s);s.adjust.saturation=-5;history.push(s);
  assert.equal(history.undo().adjust.saturation,0);
  assert.equal(history.undo().adjust.contrast,0);
  assert.equal(history.undo().operations.length,1);
  assert.deepEqual(history.undo(),freshState());
  assert.equal(history.redo().operations[0].type,'rotate');
  const isolated=history.current;isolated.operations.length=0;
  assert.equal(history.current.operations.length,1);
});
test('a new edit after undo discards obsolete redo branch',()=>{
  const h=new EditHistory(),s=freshState();s.adjust.brightness=10;h.push(s);s.adjust.brightness=20;h.push(s);
  const branch=h.undo();branch.filter='mono';h.push(branch);assert.equal(h.canRedo,false);
  assert.equal(h.current.adjust.brightness,10);assert.equal(h.current.filter,'mono');
});
test('history bounds memory, skips no-op commits and reset remains undoable',()=>{
  const h=new EditHistory(4),s=freshState();assert.equal(h.push(s),false);
  for(let i=1;i<=9;i++){s.adjust.brightness=i;h.push(s)}assert.equal(h.entries.length,4);
  h.push(freshState());assert.equal(h.undo().adjust.brightness,9);
});
test('crop ratios fit portrait, landscape and tiny images without stretching',()=>{
  for(const [w,h] of [[1200,800],[600,1000],[1,1]])for(const ratio of [1,4/3,3/2,16/9,9/16]){
    const r=centeredCrop(w,h,ratio);assert.ok(r.x>=0&&r.y>=0&&r.x+r.w<=w+.000001&&r.y+r.h<=h+.000001);
    assert.ok(Math.abs(r.w/r.h-ratio)<1e-9);
  }
});
test('all crop handles preserve locked ratios and remain within image boundaries',()=>{
  for(const ratio of [0,1,4/3,9/16])for(const handle of ['nw','n','ne','e','se','s','sw','w']){
    const rect=centeredCrop(700,500,ratio);
    for(const [dx,dy] of [[2000,2000],[-2000,-2000],[50,-25]]){
      const r=resizeCrop(rect,handle,dx,dy,700,500,ratio);
      assert.ok(r.w>0&&r.h>0&&r.x>=-1e-9&&r.y>=-1e-9&&r.x+r.w<=700+1e-9&&r.y+r.h<=500+1e-9);
      if(ratio)assert.ok(Math.abs(r.w/r.h-ratio)<1e-9);
    }
  }
});
test('moving and integer crops cannot read outside source pixels',()=>{
  const r=moveCrop({x:20,y:20,w:40,h:30},999,-999,100,80);assert.deepEqual(r,{x:60,y:0,w:40,h:30});
  assert.deepEqual(integerCrop({x:99.9,y:79.9,w:5,h:5},100,80),{x:99,y:79,w:1,h:1});
});
test('fit and export size preserve aspect ratio after crop and rotation',()=>{
  assert.ok(fitZoom(4000,3000,800,600)<1);assert.equal(fitZoom(100,80,800,600),1);
  assert.deepEqual(exportSize(300,600,1200,800,'original'),{width:600,height:1200});
  assert.deepEqual(exportSize(300,600,1200,800,'current'),{width:300,height:600});
  assert.equal(signature(freshState()),signature(freshState()));
});
test('all 32 filters at zero intensity preserve the existing Adjust settings',()=>{
  assert.equal(FILTERS.length,32);assert.equal(new Set(FILTERS.map(f=>f.id)).size,32);
  const state=freshState();state.adjust={exposure:.5,brightness:12,contrast:-7,saturation:18};
  const base=filterString(state);
  for(const filter of FILTERS){assert.equal(filterString({...state,filter:filter.id,filterIntensity:0}),base);if(filter.id!=='none')assert.notEqual(filterString({...state,filter:filter.id}),base)}
  assert.equal(filterString({...state,filter:'mono',filterIntensity:50}),base+' grayscale(0.5)');
  assert.equal(filterString({...state,filter:'mono',filterIntensity:-10}),base);
});
test('filter intensity is undoable alongside Adjust, reset and legacy default strength',()=>{
  const history=new EditHistory(),state=freshState();state.adjust.exposure=.5;state.filter='vintage';state.filterIntensity=35;history.push(state);
  state.filterIntensity=80;history.push(state);assert.equal(history.undo().filterIntensity,35);assert.equal(history.current.adjust.exposure,.5);assert.equal(history.redo().filterIntensity,80);
  history.push(freshState());assert.equal(history.undo().filter,'vintage');assert.equal(history.current.filterIntensity,80);
  const legacy={...freshState(),filter:'mono'};delete legacy.filterIntensity;assert.equal(filterString(legacy),filterString({...legacy,filterIntensity:100}));
});
