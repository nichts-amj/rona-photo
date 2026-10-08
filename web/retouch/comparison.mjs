// Comparison changes only the displayed canvas, never the edit or export source.
export function drawWipe(context,before,after,width,height,percent){
  const split=Math.max(0,Math.min(100,Number(percent)||0))/100*width;
  context.clearRect(0,0,width,height);
  context.drawImage(after,0,0,width,height);
  if(split>0){
    context.save();context.beginPath();context.rect(0,0,split,height);context.clip();
    context.drawImage(before,0,0,width,height);context.restore();
  }
  return split;
}
