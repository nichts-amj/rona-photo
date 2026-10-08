import {freshState,renderGeometry,drawPreview,encodeExport,EditHistory} from '../engine.mjs';
const assert=(condition,message)=>{if(!condition)throw Error(message)};
const pixel=(canvas,x,y)=>Array.from(canvas.getContext('2d').getImageData(x,y,1,1).data);
const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
async function decode(blob){const url=URL.createObjectURL(blob);try{const image=new Image();image.src=url;await image.decode();return image}finally{URL.revokeObjectURL(url)}}
document.getElementById('run').onclick=async()=>{
  const list=document.getElementById('results');list.replaceChildren();let passed=0,failed=0;
  async function check(name,action){const row=document.createElement('li');try{await action();row.textContent='LULUS · '+name;passed++}catch(e){row.textContent='GAGAL · '+name+': '+e.message;failed++}list.append(row)}
  const source=document.createElement('canvas');source.width=40;source.height=30;
  const ctx=source.getContext('2d');ctx.fillStyle='rgb(100,50,25)';ctx.fillRect(0,0,20,15);ctx.fillStyle='rgb(20,120,60)';ctx.fillRect(20,0,20,15);ctx.fillStyle='rgb(30,60,140)';ctx.fillRect(0,15,20,15);
  const original=await decode(await encodeExport(source,'image/png',1,{width:40,height:30}));
  const state=freshState();let current=renderGeometry(original,[]);
  await check('Original transparan tetap utuh',()=>{assert(same(pixel(current,5,5),[100,50,25,255]),'pixel berubah');assert(pixel(current,25,25)[3]===0,'alpha berubah')});
  await check('Rotate kanan 90° mempertahankan piksel',()=>{current=renderGeometry(original,[{type:'rotate',direction:1}]);assert(current.width===30&&current.height===40,'dimensi');assert(same(pixel(current,24,5),[100,50,25,255]),'orientasi salah')});
  await check('Rotate kiri dan flip horizontal/vertical benar',()=>{
    const left=renderGeometry(original,[{type:'rotate',direction:-1}]);assert(same(pixel(left,5,34),[100,50,25,255]),'rotate kiri');
    const x=renderGeometry(original,[{type:'flip',axis:'x'}]);assert(same(pixel(x,34,5),[100,50,25,255]),'flip x');
    const y=renderGeometry(original,[{type:'flip',axis:'y'}]);assert(same(pixel(y,5,24),[100,50,25,255]),'flip y');
  });
  await check('Crop mengambil area yang tepat',()=>{current=renderGeometry(original,[{type:'crop',x:20,y:0,w:10,h:10}]);assert(current.width===10&&current.height===10,'dimensi');assert(same(pixel(current,5,5),[20,120,60,255]),'area salah')});
  await check('Brightness mengubah piksel dan Undo/Redo mengembalikan state',()=>{
    const h=new EditHistory();state.adjust.brightness=20;h.push(state);const p=document.createElement('canvas');drawPreview(renderGeometry(original,[]),h.current,p);
    assert(Math.abs(pixel(p,5,5)[0]-120)<=1,'brightness tidak diterapkan');drawPreview(renderGeometry(original,[]),h.undo(),p);assert(same(pixel(p,5,5),[100,50,25,255]),'undo');drawPreview(renderGeometry(original,[]),h.redo(),p);assert(Math.abs(pixel(p,5,5)[0]-120)<=1,'redo');
  });
  await check('Reset dan render ulang tidak mengubah original',()=>{const neutral=renderGeometry(original,[]);assert(same(pixel(neutral,5,5),pixel(source,5,5)),'source dimodifikasi')});
  await check('AI snapshot satu history step, Undo/Redo dan crop setelah AI tetap tepat',async()=>{
    const h=new EditHistory(),before=freshState();before.operations=[{type:'crop',x:20,y:0,w:10,h:10}];before.adjust.brightness=20;h.push(before);
    const beforeCanvas=document.createElement('canvas');drawPreview(renderGeometry(original,before.operations),before,beforeCanvas);const beforePixel=pixel(beforeCanvas,5,5);
    const ai=document.createElement('canvas');ai.width=10;ai.height=10;const ac=ai.getContext('2d');ac.fillStyle='rgb(45,145,85)';ac.fillRect(0,0,10,10);
    const after=freshState();after.operations=[...before.operations,{type:'retouch',id:'test-ai'}];h.push(after);
    const decoded=await decode(await encodeExport(ai,'image/png',1,{width:10,height:10}));
    const resolve=id=>id==='test-ai'?decoded:null,preview=document.createElement('canvas');
    drawPreview(renderGeometry(original,h.current.operations,resolve),h.current,preview);assert(same(pixel(preview,5,5),[45,145,85,255]),'snapshot');
    const undo=h.undo();drawPreview(renderGeometry(original,undo.operations,resolve),undo,preview);assert(same(pixel(preview,5,5),beforePixel),'Undo pre-AI adjust');
    const redo=h.redo();drawPreview(renderGeometry(original,redo.operations,resolve),redo,preview);assert(same(pixel(preview,5,5),[45,145,85,255]),'Redo');
    const crop=renderGeometry(original,[...redo.operations,{type:'crop',x:2,y:2,w:4,h:5}],resolve);assert(crop.width===4&&crop.height===5,'crop setelah snapshot');
    assert(same(pixel(renderGeometry(original,[]),5,5),[100,50,25,255]),'original berubah');
  });
  await check('Exposure, contrast, saturation dan filter mengubah piksel',()=>{
    const p=document.createElement('canvas'),geo=renderGeometry(original,[]);
    let s=freshState();s.adjust.exposure=1;drawPreview(geo,s,p);assert(Math.abs(pixel(p,5,5)[0]-200)<=1,'exposure');
    s=freshState();s.adjust.contrast=20;drawPreview(geo,s,p);assert(pixel(p,5,5)[0]<100,'contrast');
    s=freshState();s.adjust.saturation=-100;drawPreview(geo,s,p);let rgb=pixel(p,5,5);assert(rgb[0]===rgb[1]&&rgb[1]===rgb[2],'saturation');
    s=freshState();s.filter='mono';drawPreview(geo,s,p);rgb=pixel(p,5,5);assert(rgb[0]===rgb[1]&&rgb[1]===rgb[2],'filter');
  });
  for(const type of ['image/png','image/jpeg','image/webp'])await check('Export '+type+' dapat didecode kembali',async()=>{
    const blob=await encodeExport(source,type,.95,{width:40,height:30});const im=await decode(blob);assert(im.naturalWidth===40&&im.naturalHeight===30,'dimensi salah');assert(blob.type===type&&blob.size>0,'format salah');
    const pixels=renderGeometry(im,[]);assert(Math.abs(pixel(pixels,5,5)[0]-100)<8,'warna rusak');
    if(type==='image/jpeg')assert(pixel(pixels,25,25)[0]>245,'JPEG tidak putih');else assert(pixel(pixels,25,25)[3]===0,'alpha hilang');
  });
  document.getElementById('summary').textContent=`${passed} lulus · ${failed} gagal`;
};
