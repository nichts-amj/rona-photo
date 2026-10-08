import test from 'node:test';
import assert from 'node:assert/strict';
import {resolutionPlan,workingOriginalSize} from '../web/retouch/resolution.mjs';
import {renderGeometry,EditHistory,freshState} from '../web/retouch/engine.mjs';

test('prompt starts at 50% above 2000 px and slider supports 0 to 90%',()=>{
  assert.equal(resolutionPlan(2000,1536),null);
  assert.equal(resolutionPlan(1200,2000),null);
  assert.deepEqual(resolutionPlan(2001,1000).after,{width:1001,height:500});
  assert.equal(resolutionPlan(5000,3000).reduction,50);
  assert.deepEqual(resolutionPlan(4000,3000,90).after,{width:400,height:300});
  assert.deepEqual(resolutionPlan(4000,3000,0).after,{width:4000,height:3000});
  assert.equal(resolutionPlan(4000,3000,100).reduction,90);
  assert.equal(resolutionPlan(4000,3000,-5).reduction,0);
  assert.deepEqual(resolutionPlan(3001,5001,25).after,{width:2251,height:3751});
});
test('working Before and export sizes follow manual reductions, with legacy 50% compatibility',()=>{
  for(const [width,height] of [[4096,3072],[3000,1500],[2500,1500]]){
    const plan=resolutionPlan(width,height,90);
    assert.deepEqual(workingOriginalSize(width,height,[{type:'resize',reason:'performance',scale:plan.scale}]),plan.after);
  }
  assert.deepEqual(workingOriginalSize(4096,3072,[{type:'resize',reason:'performance',width:2048,height:1536}]),{width:2048,height:1536});
});

function canvases(){
  const draws=[];
  globalThis.document={createElement(){const c={width:0,height:0};c.getContext=()=>({drawImage(...args){draws.push({target:[c.width,c.height],args})}});return c}};
  return draws;
}
test('reduced geometry replays from untouched upload and Undo restores its full dimensions',()=>{
  const draws=canvases(),source={naturalWidth:4096,naturalHeight:3072};
  const history=new EditHistory(),state=freshState();
  state.operations.push({type:'resize',reason:'performance',width:2048,height:1536});history.push(state);
  let result=renderGeometry(source,history.current.operations);
  assert.deepEqual([result.width,result.height],[2048,1536]);
  assert.deepEqual(draws.at(-1).args.slice(-4),[0,0,2048,1536]);
  result=renderGeometry(source,history.undo().operations);
  assert.deepEqual([result.width,result.height],[4096,3072]);
  assert.deepEqual([source.naturalWidth,source.naturalHeight],[4096,3072]);
  const restored=JSON.parse(JSON.stringify(history.redo()));
  assert.deepEqual(workingOriginalSize(4096,3072,restored.operations),{width:2048,height:1536});
});
test('an AI snapshot following compression is not reduced a second time on history replay',()=>{
  canvases();
  const ops=[{type:'resize',reason:'performance',width:2048,height:1536},{type:'retouch',id:'ai-result'}];
  const result=renderGeometry({naturalWidth:4096,naturalHeight:3072},ops,()=>({naturalWidth:2048,naturalHeight:1536}));
  assert.deepEqual([result.width,result.height],[2048,1536]);
  assert.deepEqual(workingOriginalSize(4096,3072,ops),{width:2048,height:1536});
});
