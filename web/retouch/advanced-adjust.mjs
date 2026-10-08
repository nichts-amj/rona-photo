export const ADVANCED_ADJUSTMENTS=['highlights','shadows','temperature','tint','vibrance','whites','blacks'];
const limit=value=>Number.isFinite(value)?Math.max(-100,Math.min(100,value)):0;
export function applyAdvancedAdjust(pixels,settings){
  const [highlights,shadows,temperature,tint,vibrance,whites,blacks]=ADVANCED_ADJUSTMENTS.map(key=>limit(settings[key]));
  if(![highlights,shadows,temperature,tint,vibrance,whites,blacks].some(Boolean))return false;
  const high=highlights*.64,shadow=shadows*.64,warm=temperature*.24,green=tint*.18,vivid=vibrance/100*.7;
  for(let i=0;i<pixels.length;i+=4){
    if(pixels[i+3]===0)continue;
    let r=pixels[i],g=pixels[i+1],b=pixels[i+2];
    const luminance=(.2126*r+.7152*g+.0722*b)/255;
    const whiteWeight=Math.max(0,(luminance-.55)/.45),blackWeight=Math.max(0,(.45-luminance)/.45);
    const tone=high*luminance**3+shadow*(1-luminance)**3+whites*.64*whiteWeight**2+blacks*.64*blackWeight**2;
    r+=tone+warm+green*.5;g+=tone-green;b+=tone-warm+green*.5;
    const max=Math.max(r,g,b),min=Math.min(r,g,b),saturation=(max-min)/Math.max(1,max);
    const factor=1+vivid*(vivid>0?1-Math.max(0,Math.min(1,saturation)):1);
    const gray=.2126*r+.7152*g+.0722*b;
    pixels[i]=Math.round(Math.max(0,Math.min(255,gray+(r-gray)*factor)));
    pixels[i+1]=Math.round(Math.max(0,Math.min(255,gray+(g-gray)*factor)));
    pixels[i+2]=Math.round(Math.max(0,Math.min(255,gray+(b-gray)*factor)));
  }
  return true;
}
