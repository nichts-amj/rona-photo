export const HSL_COLORS=[
  {id:'red',name:'Merah',hue:0,color:'#dd5252'},
  {id:'orange',name:'Jingga',hue:30,color:'#ed9444'},
  {id:'yellow',name:'Kuning',hue:60,color:'#d7bf39'},
  {id:'green',name:'Hijau',hue:120,color:'#55a36c'},
  {id:'cyan',name:'Cyan',hue:180,color:'#45aab6'},
  {id:'blue',name:'Biru',hue:240,color:'#5489d7'},
  {id:'purple',name:'Ungu',hue:270,color:'#9866c9'},
  {id:'magenta',name:'Magenta',hue:300,color:'#cf5ca0'}
];
const value=(n,max)=>Number.isFinite(n)?Math.max(-max,Math.min(max,n)):0;
export const hslHasChanges=hsl=>HSL_COLORS.some(c=>['hue','saturation','luminance'].some(k=>value(hsl?.[c.id]?.[k],k==='hue'?180:100)!==0));
export const adjustHasChanges=adjust=>Object.entries(adjust||{}).some(([k,v])=>k==='hsl'?hslHasChanges(v):Number.isFinite(v)&&v!==0);
// Interpolate neighbouring colour bands using the source hue, never a modified hue.
export function hueWeights(hue){
  hue=((hue%360)+360)%360;
  let index=HSL_COLORS.findLastIndex(c=>c.hue<=hue);
  const next=(index+1)%HSL_COLORS.length,end=next?HSL_COLORS[next].hue:360;
  const t=(hue-HSL_COLORS[index].hue)/(end-HSL_COLORS[index].hue);
  const smooth=t*t*(3-2*t);
  return [[HSL_COLORS[index].id,1-smooth],[HSL_COLORS[next].id,smooth]];
}
export function applyHSL(data,hsl){
  if(!hslHasChanges(hsl))return;
  const settings=Object.fromEntries(HSL_COLORS.map(c=>[c.id,[value(hsl?.[c.id]?.hue,180),value(hsl?.[c.id]?.saturation,100)/100,value(hsl?.[c.id]?.luminance,100)/100]]));
  for(let i=0;i<data.length;i+=4){
    if(!data[i+3])continue;
    const r=data[i]/255,g=data[i+1]/255,b=data[i+2]/255,max=Math.max(r,g,b),min=Math.min(r,g,b),delta=max-min;
    if(delta<1/255)continue;
    let l=(max+min)/2,s=delta/(1-Math.abs(2*l-1));
    let h=(max===r?((g-b)/delta)%6:max===g?(b-r)/delta+2:(r-g)/delta+4)*60;if(h<0)h+=360;
    const protection=Math.min(1,s/.15);
    let band=7;while(band>0&&HSL_COLORS[band].hue>h)band--;
    const next=(band+1)%8,end=next?HSL_COLORS[next].hue:360;
    const t=(h-HSL_COLORS[band].hue)/(end-HSL_COLORS[band].hue),weight=t*t*(3-2*t);
    const a=settings[HSL_COLORS[band].id],bnext=settings[HSL_COLORS[next].id];
    let dh=a[0]*(1-weight)+bnext[0]*weight,ds=a[1]*(1-weight)+bnext[1]*weight,dl=a[2]*(1-weight)+bnext[2]*weight;
    if(!dh&&!ds&&!dl)continue;
    h=((h+dh*protection)%360+360)%360;ds*=protection;dl*=protection;
    s=ds>=0?s+(1-s)*ds:s*(1+ds);l=dl>=0?l+(1-l)*dl:l*(1+dl);
    const chroma=(1-Math.abs(2*l-1))*s,x=chroma*(1-Math.abs((h/60)%2-1)),m=l-chroma/2;
    let rr=0,gg=0,bb=0;
    if(h<60){rr=chroma;gg=x}else if(h<120){rr=x;gg=chroma}else if(h<180){gg=chroma;bb=x}else if(h<240){gg=x;bb=chroma}else if(h<300){rr=x;bb=chroma}else{rr=chroma;bb=x}
    data[i]=Math.round((rr+m)*255);data[i+1]=Math.round((gg+m)*255);data[i+2]=Math.round((bb+m)*255);
  }
}
