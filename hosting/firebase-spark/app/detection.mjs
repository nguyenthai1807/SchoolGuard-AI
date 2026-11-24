// Decoder for the explicitly exported [1,84,2100] COCO model, not arbitrary ONNX.
export function iou(a,b){
  const intersection=Math.max(0,Math.min(a[2],b[2])-Math.max(a[0],b[0]))*Math.max(0,Math.min(a[3],b[3])-Math.max(a[1],b[1]));
  return intersection/Math.max(1e-8,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection);
}
export function decode(data,dims,width,height,threshold=.4){
  if(dims.length!==3||dims[0]!==1||dims[1]!==84)throw Error('Model không đúng cấu trúc đã kiểm thử.');
  const n=dims[2],scale=Math.min(320/width,320/height);
  const left=Math.floor((320-Math.round(width*scale))/2),top=Math.floor((320-Math.round(height*scale))/2);
  const boxes=[];
  for(let i=0;i<n;i++){
    const score=data[4*n+i]; // COCO class 0: person; no separate objectness.
    if(!Number.isFinite(score)||score<threshold)continue;
    let isPerson=true;for(let c=5;c<84;c++)if(data[c*n+i]>score){isPerson=false;break;}
    if(!isPerson)continue;
    const x=data[i],y=data[n+i],w=data[2*n+i],h=data[3*n+i];
    const box=[Math.max(0,(x-w/2-left)/scale),Math.max(0,(y-h/2-top)/scale),Math.min(width,(x+w/2-left)/scale),Math.min(height,(y+h/2-top)/scale),score];
    if(box.every(Number.isFinite)&&box[2]>box[0]&&box[3]>box[1])boxes.push(box);
  }
  boxes.sort((a,b)=>b[4]-a[4]);const kept=[];
  for(const box of boxes){if(kept.every(other=>iou(box,other)<.45))kept.push(box);if(kept.length>=100)break;}
  return kept;
}
