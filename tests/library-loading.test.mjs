import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../web/library.mjs',import.meta.url),'utf8');
function fixture(cached){
 let finish;const fresh=new Promise(resolve=>finish=resolve),renders=[],loading=[];
 const cache={peek:()=>cached,read:()=>cached,save(){}};
 const context={listing:null,refreshing:null,cacheSession:'',token:'',galleryCache:cache,loading:value=>loading.push(value),displayListing:()=>renders.push(context.listing),api:async path=>path==='/api/bootstrap'?{token:'server'}:fresh,$:()=>({replaceChildren(){}})};
 vm.createContext(context);vm.runInContext(source.slice(source.indexOf('async function refresh('),source.indexOf("$('filter').onchange")),context);
 return {context,renders,loading,finish};
}
test('second opening renders cache before network finishes, with no loading bar or unchanged-grid replacement',async()=>{
 const cached={items:[{id:'one'}]},p=fixture(cached);const pending=p.context.refresh(true);
 assert.equal(p.renders[0],cached);assert.deepEqual(p.loading,[false]);
 p.finish(cached);await pending;assert.equal(p.renders.length,1);assert(!p.loading.includes(true));
});
test('new history replaces the provisional cache after the background response',async()=>{
 const cached={items:[{id:'one'}]},fresh={items:[{id:'one'},{id:'two'}]},p=fixture(cached);const pending=p.context.refresh(true);
 p.finish(fresh);await pending;assert.equal(p.renders.at(-1).items.length,2);assert(!p.loading.includes(true));
});
test('first opening shows a loading bar until results arrive',async()=>{
 const p=fixture(null);const pending=p.context.refresh(true);assert.equal(p.loading[0],true);
 p.finish({items:[]});await pending;assert.equal(p.loading.at(-1),false);assert.equal(p.renders.length,1);
});
