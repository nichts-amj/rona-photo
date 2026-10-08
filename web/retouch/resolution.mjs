// Optional reduction based on the longest side; the upload stays intact.
export function resolutionPlan(width,height,reduction=50){
  if(!Number.isInteger(width)||!Number.isInteger(height)||width<1||height<1)return null;
  if(Math.max(width,height)<=2000)return null;
  reduction=Math.max(0,Math.min(90,Math.round(Number(reduction)||0)));
  const scale=(100-reduction)/100;
  return {before:{width,height},after:{width:Math.max(1,Math.round(width*scale)),height:Math.max(1,Math.round(height*scale))},reduction,scale};
}
export function workingOriginalSize(width,height,operations){
  for(const op of operations){
    if(op.type==='resize'&&op.reason==='performance'){
      // Older saved edits used a fixed 50% reduction without a scale field.
      const scale=op.scale??0.5;
      width=Math.max(1,Math.round(width*scale));height=Math.max(1,Math.round(height*scale));
    }
  }
  return {width,height};
}
