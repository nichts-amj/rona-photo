import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../web/studio-v2.js',import.meta.url),'utf8');
function setup(){
 const nodes=new Map();
 const node=id=>{if(!nodes.has(id))nodes.set(id,{value:'',textContent:''});return nodes.get(id)};
 const context={document:{getElementById:node},names:{B:'Real-ESRGAN',H:'HAT',S:'Swin2SR',A:'SwinIR',F:'codeFormer',G:'GFPGAN'},preferredDevice:'cpu',updateLabels(){},modeUI(){}};
 vm.createContext(context);
 for(const name of ['defaults','configName','scaleAllowed','configure','readConfig','resetMode'])vm.runInContext(source.split('\n').find(line=>line.startsWith('function '+name+'(')),context);
 return {context,node};
}
test('native defaults and saved 2x configuration survive loading',()=>{
 const {context:c,node}=setup();
 for(const model of ['B','H','S','A','F','G']){
  const config=c.defaults('single-'+model);
  assert.equal(config.output_scale,['B','H','S'].includes(model)?4:2);
  node('mode').value='single';node('single-model').value=model;c.configure(config);
  assert.equal(c.readConfig().output_scale,config.output_scale);
 }
 node('single-model').value='B';c.configure({...c.defaults('single-B'),output_scale:2});assert.equal(c.readConfig().output_scale,2);
 const old=c.defaults('single-B');delete old.output_scale;c.configure(old);assert.equal(c.readConfig().output_scale,2);
});
test('custom output restricted by contributing or protected SwinIR',()=>{
 const {context:c,node}=setup();node('mode').value='custom';
 c.configure({...c.defaults('custom'),weights:{B:50,H:50},reference:'B',output_scale:4});
 assert.equal(c.readConfig().output_scale,4);
 node('wa').value=1;assert.equal(c.readConfig().output_scale,2);
 node('wa').value=0;node('reference').value='A';assert.equal(c.readConfig().output_scale,2);
});
test('model ordering and scale placement precede cloning comparison configuration',()=>{
 const html=fs.readFileSync(new URL('../web/index.html',import.meta.url),'utf8');
 const select=html.match(/id="single-model">([\s\S]*?)<\/select>/)[1];
 assert.deepEqual([...select.matchAll(/value="(\w)"/g)].map(m=>m[1]),['B','H','S','A','F','G']);
 assert.ok(html.indexOf('id="scale-field"')<html.indexOf('id="face-option"'));
 assert.ok(source.indexOf("['wb','wh','ws','wa']")<source.indexOf("cloneNode(true)"));
 assert.ok(html.includes('Potongan Swin<select'));assert.ok(!html.includes('Potongan SwinIR / Swin2SR'));
});
