import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const source=fs.readFileSync(new URL('../web/studio-v2.js',import.meta.url),'utf8');
const start=source.indexOf('function upscaleConfig('),end=source.indexOf('function configure(',start);
const migrate=new Function('upscaleModels','names',source.slice(start,end)+';return upscaleConfig;')(['B','S','H'],{B:'Real-ESRGAN',H:'HAT',S:'Swin2SR',A:'SwinIR'});
test('legacy mixed presets lose face restoration without changing upscale weights',()=>{
 const raw={weights:{B:60,H:40,F:20,G:10},reference:'H',face_model:'F',fidelity:.8,face_mix:.7,output_scale:4,use_mask:true};
 const result=migrate(raw);
 assert.deepEqual(result.weights,{B:60,S:0,H:40});assert.equal(result.face_model,'');assert.equal(result.label,'Real-ESRGAN + HAT');assert.equal(result.reference,'H');assert.equal(result.output_scale,4);assert(!('fidelity' in result));assert(!('face_mix' in result));assert.equal(raw.face_model,'F');
});
test('face-only legacy presets fall back to Real-ESRGAN for a valid new job',()=>{
 const result=migrate({weights:{G:100},face_model:'',reference:'G',use_mask:false,output_scale:2});
 assert.deepEqual(result.weights,{B:100,S:0,H:0});assert.equal(result.label,'Real-ESRGAN');assert.equal(result.output_scale,4);assert.equal(result.face_model,'');assert.equal(result.reference,'S');
});

test('SwinIR weights and protected reference migrate to Swin2SR in model order',()=>{
 const raw={weights:{A:65,B:35,S:0,H:0},reference:'A',output_scale:2,use_mask:true};
 const result=migrate(raw);
 assert.deepEqual(result.weights,{B:35,S:65,H:0});assert.equal(result.reference,'S');assert.equal(result.label,'Real-ESRGAN + Swin2SR');assert.equal(result.output_scale,2);assert.equal(raw.weights.A,65);
});
test('merged contributions retain ratios when the Swin2SR slider would exceed 100',()=>{
 const result=migrate({weights:{A:80,S:80,B:80,H:40},reference:'A'});
 assert.deepEqual(result.weights,{B:50,S:100,H:25});assert(!('A' in result.weights));
});
