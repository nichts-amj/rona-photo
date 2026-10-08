import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {drawWipe} from '../web/retouch/comparison.mjs';

// Tiny software canvas exercises pixel output rather than just matching method calls.
function canvas(width,height){
  const pixels=new Array(width*height).fill(null);let clip=width,stack=[],rect=width;
  const context={
    clearRect(){pixels.fill(null)},
    drawImage(image){for(let y=0;y<height;y++)for(let x=0;x<width;x++)if(x<clip)pixels[y*width+x]=image.pixels[y*width+x]},
    save(){stack.push(clip)},restore(){clip=stack.pop()},beginPath(){},rect(x,y,w,h){rect=w},clip(){clip=rect}
  };
  return {context,pixels};
}
test('wipe shows Before on the left, After on the right and full endpoints',()=>{
  const before={pixels:[1,2,3,4,5,6,7,8]},after={pixels:[11,12,13,14,15,16,17,18]};
  const original=before.pixels.slice();
  for(const [percent,expected] of [[0,after.pixels],[50,[1,2,13,14,5,6,17,18]],[100,before.pixels],[-20,after.pixels],[150,before.pixels]]){
    const output=canvas(4,2);drawWipe(output.context,before,after,4,2,percent);assert.deepEqual(output.pixels,expected);
  }
  assert.deepEqual(before.pixels,original);
});
test('comparison is limited to Retouch and retained Apply result; toggle and Before bypass wipe',async()=>{
  const source=await readFile(new URL('../web/retouch/editor.mjs',import.meta.url),'utf8');
  const body=source.slice(source.indexOf('function drawComparison(source){'),source.indexOf("$('retouch-comparison-range').oninput"));
  const execute=new Function('tool','before','comparisonSource','retouch','comparisonCommittedKey','signature','editState','comparisonEnabled','preview','$','drawWipe',body+';return drawComparison({});');
  const nodes=new Map();const $=id=>{if(!nodes.has(id))nodes.set(id,{style:{},value:50,setAttribute(){}});return nodes.get(id)};
  let draws=0;const wipe=()=>draws++;
  const run=(tool,before,temporary,committed,enabled=true)=>execute(tool,before,{}, {temporary},committed,()=> 'applied',{},enabled,{width:100,height:80,getContext(){return {}}},$,wipe);
  assert.equal(run('retouch',false,true,null),true);
  assert.equal(run('retouch',false,false,'applied'),true);
  assert.equal(run('retouch',false,false,'old'),false);
  assert.equal(run('adjust',false,true,null),false);
  assert.equal(run('retouch',true,true,null),false);
  assert.equal(run('retouch',false,true,null,false),false);
  assert.equal(draws,2);
});
