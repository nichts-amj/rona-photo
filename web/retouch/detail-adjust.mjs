const clamp=(value,min,max)=>Math.max(min,Math.min(max,value));
const amount=(value,min)=>Number.isFinite(value)?clamp(value,min,100):0;
const luminance=(pixels,index)=>pixels[index]*.2126+pixels[index+1]*.7152+pixels[index+2]*.0722;

export function applyDetailAdjust(pixels,width,height,settings){
  const sharp=amount(settings.sharpness,0)/100*.65,vignette=amount(settings.vignette,-100)/100;
  if(!sharp&&!vignette)return false;
  if(!width||!height||pixels.length!==width*height*4)throw Error('Dimensi detail foto tidak valid.');
  // Copy only for sharpening: neighbours must never read already processed pixels.
  const source=sharp?new Uint8ClampedArray(pixels):null;
  for(let y=0;y<height;y++)for(let x=0;x<width;x++){
    const index=(y*width+x)*4;if(pixels[index+3]===0)continue;
    let detail=0;
    if(sharp){
      const left=x?index-4:index,right=x+1<width?index+4:index,up=y?index-width*4:index,down=y+1<height?index+width*4:index;
      const la=source[left+3]/255,ra=source[right+3]/255,ua=source[up+3]/255,da=source[down+3]/255;
      const weight=la+ra+ua+da,sum=luminance(source,left)*la+luminance(source,right)*ra+luminance(source,up)*ua+luminance(source,down)*da;
      const difference=luminance(source,index)-sum/Math.max(weight,.0001);
      if(Math.abs(difference)>2)detail=clamp(difference*sharp,-24,24);
    }
    let shade=0;
    if(vignette){
      const nx=width>1?x/(width-1)*2-1:0,ny=height>1?y/(height-1)*2-1:0;
      const radius=clamp((nx*nx+ny*ny-.25)/1.75,0,1);shade=radius*radius*(3-2*radius)*Math.abs(vignette)*.65;
    }
    for(let channel=0;channel<3;channel++){
      let value=clamp((source?source[index+channel]:pixels[index+channel])+detail,0,255);
      if(shade)value=vignette>0?value*(1-shade):value+(255-value)*shade;
      pixels[index+channel]=Math.round(value);
    }
  }
  return true;
}
