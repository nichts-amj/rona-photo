import test from 'node:test';
import assert from 'node:assert/strict';
import {AIRetouchController} from '../web/retouch/ai-controller.mjs';

function fixture(){
  const nodes=new Map(),notices=[];
  globalThis.document={getElementById(id){if(!nodes.has(id))nodes.set(id,{dataset:{},classList:{toggle(){}},setAttribute(){},hidden:false,disabled:false,value:0});return nodes.get(id)}};
  globalThis.window={addEventListener(){}};
  const controller=new AIRetouchController({hasImage:()=>true,signature:()=> 'photo-1',source:async()=>({}),flush(){},lock(){},restore(){},notice:(...args)=>notices.push(args)});
  controller.visible=true;controller.schedule=()=>{};
  controller.service.status=async()=>({debug:false});
  controller.service.upload=async()=>({document:'test',revision:1});
  controller.service.cancel=async()=>({ok:true});
  return {controller,nodes,notices};
}
test('scan visibly waits, then enables controls and shows dismissible success notification',async()=>{
  const {controller,nodes,notices}=fixture();let finish;
  controller.service.run=()=>new Promise(resolve=>finish=resolve);
  const work=controller.analyze();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(nodes.get('ai-scan-status').dataset.state,'scanning');assert.equal(nodes.get('ai-controls').disabled,true);assert.equal(nodes.get('ai-progress').hidden,false);
  finish({faces:[{}],models:{device:'cpu'}});await work;
  assert.equal(nodes.get('ai-scan-status').dataset.state,'ready');assert.equal(nodes.get('ai-controls').disabled,false);assert.equal(nodes.get('ai-progress').hidden,true);assert.equal(nodes.get('ai-retry').hidden,true);assert.equal(notices[0][2],'success');assert.equal(notices[0][3],6000);
});
test('no face keeps AI controls disabled and reports a yellow informational result',async()=>{
  const {controller,nodes,notices}=fixture();controller.service.run=async()=>({faces:[],models:{device:'cpu'}});await controller.analyze();
  assert.equal(nodes.get('ai-scan-status').dataset.state,'empty');assert.match(nodes.get('ai-face-status').textContent,/Tidak ada wajah/);assert.equal(nodes.get('ai-controls').disabled,true);assert.equal(nodes.get('ai-apply').disabled,true);assert.equal(nodes.get('ai-retry').hidden,true);assert.equal(notices[0][2],'warning');
});
test('failure shows retry; retry recovers without changing editor pixels',async()=>{
  const {controller,nodes}=fixture();controller.service.run=async()=>{throw Error('Model tidak tersedia')};await controller.analyze();
  assert.equal(nodes.get('ai-scan-status').dataset.state,'error');assert.equal(nodes.get('ai-retry').hidden,false);assert.equal(nodes.get('ai-retry').disabled,false);
  controller.service.run=async()=>({faces:[{}],models:{device:'cpu'}});await nodes.get('ai-retry').onclick();assert.equal(nodes.get('ai-scan-status').dataset.state,'ready');assert.equal(nodes.get('ai-retry').hidden,true);
});
test('cancel during preparation preserves cancelled status and does not start inference',async()=>{
  const {controller,nodes}=fixture();let finish,calls=0;controller.service.status=()=>new Promise(resolve=>finish=resolve);controller.service.run=async()=>{calls++};
  const work=controller.analyze();await new Promise(resolve=>setImmediate(resolve));controller.cancel();finish({debug:false});await work;
  assert.equal(calls,0);assert.equal(nodes.get('ai-scan-status').dataset.state,'cancelled');assert.equal(nodes.get('ai-retry').hidden,false);assert.equal(nodes.get('ai-retry').disabled,false);assert.equal(nodes.get('ai-progress').hidden,true);
});

test('scan schedules unified preview using selected model and protected adjustable defaults',async()=>{
  const {controller,nodes}=fixture();let scheduled=0;
  nodes.get('ai-model').value='gfpgan';nodes.get('ai-smooth').value=50;nodes.get('ai-restore').value=50;nodes.get('ai-strength').value=100;nodes.get('ai-fidelity').value=80;
  for(const key of ['texture','eyes','hair','identity'])nodes.get('ai-'+key).checked=true;
  controller.schedule=()=>scheduled++;
  controller.service.run=async()=>({faces:[{bbox:[1,2,30,40]}],models:{device:'cpu'}});
  await controller.analyze();
  assert.equal(scheduled,1);assert.equal(nodes.get('ai-fidelity-field').hidden,true);
  assert.deepEqual(controller.settings(),{strokes:[],blemish:0,auto:false,smooth:50,restore:50,strength:100,texture:true,eyes:true,hair:true,identity:true,mode:'manual',model:'gfpgan',fidelity:.8});
  nodes.get('ai-smooth').value=125;nodes.get('ai-smooth').oninput();assert.equal(controller.settings().smooth,125);assert.equal(scheduled,2);
});

test('preview retains decoded pixels, rejects stale response and Cancel releases preview',async()=>{
  const {controller,nodes}=fixture();controller.analysis={faces:[{}]};
  globalThis.Image=class{async decode(){}};
  let displayed;controller.hooks.preview=image=>displayed=image;
  controller.service.run=async()=>({url:'preview.png',faces:1,models:{device:'cpu'}});
  await controller.preview();assert.equal(controller.previewImage,displayed);assert.equal(controller.temporary,true);
  let finish;controller.service.run=()=>new Promise(resolve=>finish=resolve);
  const work=controller.preview();controller.cancel();finish({url:'stale.png',faces:1});await work;
  assert.equal(controller.previewImage,null);assert.equal(controller.temporary,false);
});
test('Before release draws the retained Retouch preview instead of unedited pixels',async()=>{
  const {readFile}=await import('node:fs/promises');
  const source=await readFile(new URL('../web/retouch/editor.mjs',import.meta.url),'utf8');
  const body=source.slice(source.indexOf('function showPixels(){'),source.indexOf('function commit(){'));
  const run=new Function('before','originalImage','tool','retouch','aiEdit','currentPreview','preview','$','drawComparison','originalForBefore',body+';showPixels();');
  const original={naturalWidth:100,naturalHeight:80},current={width:100,height:80},restored={};let drawn;
  const canvas={getContext:()=>({clearRect(){},drawImage:image=>drawn=image})};
  for(const before of [true,false]){
    run(before,original,'retouch',{temporary:true,previewImage:restored},null,current,canvas,()=>({}),()=>false,()=>original);
    assert.equal(drawn,before?original:restored);
  }
});

test('menu navigation reuses face analysis and completed preview without another job or upload',()=>{
  const {controller}=fixture();let uploads=0,jobs=0,displayed=0,scheduled=0;
  controller.service.upload=async()=>{uploads++};controller.service.run=async()=>{jobs++};
  controller.hooks.preview=()=>displayed++;
  const analysis={faces:[{bbox:[1,2,3,4]}]};const image={};
  controller.analysis=analysis;controller.sourceSignature='photo-1';controller.document='existing-document';controller.revision=1;
  controller.previewImage=image;controller.temporary=true;controller.previewSettingsKey=JSON.stringify(controller.settings());
  controller.strokes.push({x:.2,y:.3,r:.01});controller.previewSettingsKey=JSON.stringify(controller.settings());
  controller.schedule=()=>scheduled++;
  for(let index=0;index<3;index++){controller.show(false);controller.show(true)}
  assert.equal(controller.analysis,analysis);assert.equal(controller.previewImage,image);assert.equal(controller.document,'existing-document');
  assert.equal(controller.strokes.length,1);assert.equal(displayed,3);assert.equal(uploads,0);assert.equal(jobs,0);assert.equal(scheduled,0);
});
test('cached no-face result is retained across menus; replacement photo releases it and queues a new scan',async()=>{
  const {controller}=fixture();let scans=0,releases=0;
  controller.analysis={faces:[]};controller.sourceSignature='photo-1';controller.document='old-document';
  controller.analyze=async()=>{scans++};controller.service.release=async()=>{releases++};
  controller.show(false);controller.show(true);await new Promise(resolve=>setTimeout(resolve,10));assert.equal(scans,0);
  await controller.resetDocument();assert.equal(releases,1);assert.equal(controller.analysis,null);assert.equal(controller.document,null);assert.equal(controller.previewImage,null);
  controller.photoLoaded();await new Promise(resolve=>setTimeout(resolve,10));assert.equal(scans,1);
});
