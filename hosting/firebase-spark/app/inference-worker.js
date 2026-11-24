import * as ort from './vendor/ort.wasm.min.mjs';
import {decode} from './detection.mjs';
let session;
const FREE_MODELS = Object.freeze({
  yolov8n: './models/yolov8n.onnx',
  yolov9t: './models/yolov9t.onnx',
  yolov10n: './models/yolov10n.onnx',
});
ort.env.wasm.numThreads=1;
ort.env.wasm.wasmPaths=new URL('./vendor/',self.location.href).href;
self.onmessage=async({data})=>{
  let frame=data.frame;
  try{
    if(data.type==='load'){
      if(!Object.hasOwn(FREE_MODELS,data.model))throw Error('Model này chưa được mở trên bản Free.');
      await session?.release?.();
      session=await ort.InferenceSession.create(FREE_MODELS[data.model],{executionProviders:['wasm']});
      self.postMessage({type:'ready',model:data.model});return;
    }
    if(!session)throw Error('Chưa tải model.');
    const started=performance.now(),width=frame.width,height=frame.height;
    const canvas=new OffscreenCanvas(320,320),ctx=canvas.getContext('2d',{willReadFrequently:true});
    ctx.fillStyle='rgb(114,114,114)';ctx.fillRect(0,0,320,320);
    const scale=Math.min(320/width,320/height),w=Math.round(width*scale),h=Math.round(height*scale);
    ctx.drawImage(frame,Math.floor((320-w)/2),Math.floor((320-h)/2),w,h);frame.close();frame=null;
    const rgba=ctx.getImageData(0,0,320,320).data,input=new Float32Array(3*320*320);
    for(let i=0;i<320*320;i++)for(let c=0;c<3;c++)input[c*320*320+i]=rgba[i*4+c]/255;
    const tensor=new ort.Tensor('float32',input,[1,3,320,320]);
    const outputs=await session.run({[session.inputNames[0]]:tensor});
    const out=outputs[session.outputNames[0]],boxes=decode(out.data,out.dims,width,height);
    for(const value of Object.values(outputs))value.dispose();tensor.dispose();
    self.postMessage({type:'result',boxes,ms:performance.now()-started});
  }catch(error){self.postMessage({type:'error',message:String(error.message||error)});}
  finally{frame?.close();}
};
