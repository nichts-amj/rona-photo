import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../web/history-cache.js',import.meta.url),'utf8');
const storage=()=>{const values=new Map();return {getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)}};
function page(session=storage(),local=storage(),type='navigate'){
 const events={},window={addEventListener:(k,f)=>events[k]=f,dispatchEvent:e=>events[e.type]?.(e)};
 vm.runInNewContext(source,{window,sessionStorage:session,localStorage:local,performance:{getEntriesByType:()=>[{type}]},Event:class{constructor(type){this.type=type}},setTimeout:()=>1,clearTimeout:()=>{}});
 return {cache:window.RonaHistoryCache,events,session,local};
}
const listing={items:[{id:'photo'}],active:false};
test('normal module navigation reuses listing and thumbnail; explicit browser reload clears them',()=>{
 const first=page();first.cache.save(listing,'server-one');first.cache.remember('/image.png','data:image/webp;base64,small');first.events.pagehide();
 const next=page(first.session,first.local);assert.equal(next.cache.read('server-one').items[0].id,'photo');assert.equal(next.cache.thumbnail('/image.png'),'data:image/webp;base64,small');
 const reset=page(first.session,first.local,'reload');assert.equal(reset.cache.read('server-one'),null);assert.equal(reset.cache.thumbnail('/image.png'),null);
});
test('application restart and active jobs do not reuse a stale gallery',()=>{
 const p=page();p.cache.save(listing,'server-one');assert.equal(p.cache.read('server-two'),null);
 p.cache.save({...listing,active:true},'server-two');assert.equal(p.cache.read('server-two'),null);
});
test('mutations mark cache stale but preserve a provisional grid during background refresh',()=>{
 const local=storage(),a=page(storage(),local),b=page(storage(),local);a.cache.save(listing,'server');b.cache.save(listing,'server');a.cache.invalidate();assert.equal(b.cache.read('server'),null);assert.equal(b.cache.peek().items[0].id,'photo');assert.equal(listing.items.length,1);
});
test('thumbnail budget is bounded and storage failures allow normal operation',()=>{
 const p=page();p.cache.save(listing,'server');p.cache.remember('/huge.png','data:image/png,'+'x'.repeat(2*1024*1024));assert.equal(p.cache.thumbnail('/huge.png'),null);
 const blocked={getItem(){throw Error()},setItem(){throw Error()},removeItem(){throw Error()}};const q=page(blocked,blocked);assert.doesNotThrow(()=>q.cache.save(listing,'server'));assert.doesNotThrow(()=>q.cache.invalidate());assert.equal(q.cache.read('server'),null);
});
