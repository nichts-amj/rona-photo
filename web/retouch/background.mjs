// Background recipes share the person mask with regional Adjust.
const images=new Map();
export const backgroundImage=data=>images.get(data)||null;
export const backgroundHasChanges=bg=>!!bg?.mask&&['blur','color','image','transparent'].includes(bg.mode)&&(bg.mode!=='blur'||bg.blur>0)&&(bg.mode!=='image'||!!bg.image);
export async function prepareBackground(state){
  const recipes=[state.background,...state.operations.map(op=>op.background)].filter(Boolean);
  const used=new Set(recipes.map(bg=>bg.image).filter(Boolean));
  for(const data of used){
    if(images.has(data))continue;
    if(typeof data!=='string'||!data.startsWith('data:image/png;base64,')||data.length>24*1024*1024)throw Error('Gambar latar tidak valid.');
    const raw=Uint8Array.from(atob(data.split(',')[1]),c=>c.charCodeAt(0));
    const url=URL.createObjectURL(new Blob([raw],{type:'image/png'}));
    const image=new Image();try{image.src=url;await image.decode()}finally{URL.revokeObjectURL(url)}
    if(image.naturalWidth*image.naturalHeight>4_194_304)throw Error('Gambar latar terlalu besar.');
    images.set(data,image);
  }
  for(const key of images.keys())if(!used.has(key))images.delete(key);
}
export function drawBackground(target,bg,mask){
  if(!backgroundHasChanges(bg))return;
  const source=document.createElement('canvas');source.width=target.width;source.height=target.height;
  source.getContext('2d').drawImage(target,0,0);
  const matte=document.createElement('canvas');matte.width=mask.width;matte.height=mask.height;
  const mc=matte.getContext('2d');mc.filter=`blur(${Math.max(0,Math.min(30,Number(bg.feather)||0))*matte.width/target.width}px)`;mc.drawImage(mask,0,0);
  const person=document.createElement('canvas');person.width=target.width;person.height=target.height;
  const pc=person.getContext('2d');pc.drawImage(source,0,0);pc.globalCompositeOperation='destination-in';pc.drawImage(matte,0,0,person.width,person.height);
  const ctx=target.getContext('2d');ctx.clearRect(0,0,target.width,target.height);
  if(bg.mode==='blur'){
    const radius=Math.max(0,Math.min(100,Number(bg.blur)||0))*Math.max(target.width,target.height)/2000;
    ctx.filter=`blur(${radius}px)`;
    // Extend the edges so blur does not leave transparent borders.
    const pad=Math.ceil(radius*3);ctx.drawImage(source,-pad,-pad,target.width+pad*2,target.height+pad*2);ctx.drawImage(source,0,0);ctx.filter='none';
  }else if(bg.mode==='color'){
    ctx.fillStyle=/^#[0-9a-f]{6}$/i.test(bg.color)?bg.color:'#e6eddd';ctx.fillRect(0,0,target.width,target.height);
  }else if(bg.mode==='image'){
    const image=images.get(bg.image);if(!image)throw Error('Gambar latar belum dimuat.');
    const scale=Math.max(target.width/image.naturalWidth,target.height/image.naturalHeight)*Math.max(1,Math.min(3,(Number(bg.scale)||100)/100));
    const w=image.naturalWidth*scale,h=image.naturalHeight*scale;
    const x=(target.width-w)*Math.max(0,Math.min(100,Number(bg.x)??50))/100,y=(target.height-h)*Math.max(0,Math.min(100,Number(bg.y)??50))/100;
    ctx.drawImage(image,x,y,w,h);
  }
  if(bg.mode!=='transparent'){ctx.globalCompositeOperation='destination-out';ctx.drawImage(matte,0,0,target.width,target.height)}
  ctx.globalCompositeOperation='lighter';ctx.drawImage(person,0,0);ctx.globalCompositeOperation='source-over';
  source.width=person.width=matte.width=0;
}
