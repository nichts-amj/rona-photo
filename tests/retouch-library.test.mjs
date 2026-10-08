import test from 'node:test';
import assert from 'node:assert/strict';
import {RetouchLibrary} from '../web/retouch/library-client.mjs';

function fixture(){
 const calls=[];let fail=false;
 globalThis.fetch=async(path,options={})=>{
  calls.push({path,options});
  if(path==='/api/retouch/status')return {ok:true,json:async()=>({token:'session'})};
  if(fail&&path.includes('/result/'))return {ok:false,json:async()=>({error:'Disk penuh'})};
  return {ok:true,json:async()=>path.endsWith('/source')?{id:'photo'}:path.endsWith('/state')?{id:'photo',run:'run'}:{saved:true}};
 };
 const library=new RetouchLibrary();library.reset(new Blob(['source']),{module:'upscale',id:'old'});
 const request={name:'keluarga.png',state:{operations:[{type:'retouch',id:'snapshot'}]},settings:{retouch:{model:'codeformer'}},tool:'retouch',snapshots:[{id:'snapshot',url:'/api/retouch/result/doc/result.png'}],result:new Blob(['result'])};
 return {library,calls,request,fail:()=>fail=true};
}
test('history saves source once, recipe and snapshot references, then full result; unchanged image reuses saved version',async()=>{
 const {library,calls,request}=fixture();await library.save(request);
 assert.deepEqual(calls.map(c=>c.path),['/api/retouch/status','/api/library/retouch/source','/api/library/retouch/state','/api/library/retouch/result/photo/run']);
 assert.equal(calls[1].options.headers['X-Studio-Token'],'session');
 assert.deepEqual(JSON.parse(calls[2].options.body).snapshots,request.snapshots);
 const count=calls.length;assert.equal((await library.save(request)).reused,true);assert.equal(calls.length,count+1);assert.ok(calls.at(-1).path.startsWith('/api/library/item/retouch/'));
 await library.save({...request,state:{...request.state,filter:'warm'}});assert.equal(calls.filter(c=>c.path.endsWith('/source')).length,1);
});
test('failed result write never marks the version saved and replacement photo resets ownership',async()=>{
 const {library,request,fail}=fixture();fail();await assert.rejects(library.save(request),/Disk penuh/);assert.equal(library.signature,null);
 library.reset(new Blob(['replacement']));assert.equal(library.id,null);assert.equal(library.parent,null);assert.equal(library.signature,null);
});
