import {EFFORTS,effortInterval} from './effort.mjs';
const $=id=>document.getElementById(id),video=$('video'),canvas=$('result'),ctx=canvas.getContext('2d');
const modelSelect=$('model');
const effortLabel=document.createElement('label'),effortSelect=document.createElement('select');
effortLabel.textContent='Mức xử lý (effort) ';effortSelect.id='effort';
for(const [value,profile]of Object.entries(EFFORTS)){const option=document.createElement('option');option.value=value;option.textContent=profile.label;effortSelect.append(option);}
effortSelect.value='medium';effortLabel.append(effortSelect);document.querySelector('.controls').append(effortLabel);
const effortNote=document.createElement('p');effortNote.textContent='Mức cao lấy mẫu thường xuyên hơn, không đảm bảo chính xác hơn ở từng ảnh. Tốc độ thực tế phụ thuộc máy; chỉ có một khung hình được xử lý mỗi lần.';effortLabel.after(effortNote);
const worker=new Worker('/inference-worker.js',{type:'module'});
let ready=false,running=false,busy=false,stream=null,url=null,generation=0,submittedGeneration=0;
const status=text=>$('status').textContent=text;
function stop(){running=false;generation++;video.pause();if(stream){stream.getTracks().forEach(t=>t.stop());stream=null;video.srcObject=null;}$('stop').disabled=true;$('start').disabled=!ready;status('Đã dừng phân tích.');}
function reset(){stop();if(url){URL.revokeObjectURL(url);url=null;}video.removeAttribute('src');video.load();$('warning').textContent='';$('count').textContent='Chưa có kết quả.';}
$('load').onclick=()=>{$('load').disabled=true;status('Đang tải '+modelSelect.selectedOptions[0].textContent+' và bộ chạy AI. Lần đầu có thể mất một lúc…');worker.postMessage({type:'load',model:modelSelect.value});};
modelSelect.onchange=()=>{stop();ready=false;$('load').disabled=false;$('file').disabled=true;$('camera').disabled=true;$('start').disabled=true;status('Đã đổi model. Bấm Tải AI để tiếp tục.');};
worker.onmessage=({data})=>{
  busy=false;
  if(data.type==='ready'){ready=true;$('file').disabled=false;$('camera').disabled=false;status(data.model.toUpperCase()+' sẵn sàng. Chọn video hoặc mở webcam.');return;}
  if(data.type==='error'){stop();if(!ready)$('load').disabled=false;status('Không chạy được AI: '+data.message);return;}
  if(submittedGeneration!==generation)return;
  ctx.strokeStyle='#78f5d2';ctx.fillStyle='#78f5d2';ctx.lineWidth=3;ctx.font='18px sans-serif';
  for(const [x1,y1,x2,y2,score]of data.boxes){ctx.strokeRect(x1,y1,x2-x1,y2-y1);ctx.fillText(`Người ${Math.round(score*100)}%`,x1,Math.max(20,y1-5));}
  $('count').textContent=`Đang thấy ${data.boxes.length} người trong khung hình lấy mẫu.`;
  $('speed').textContent=`Xử lý AI: ${Math.round(data.ms)} ms/khung hình. Kết quả không xác định danh tính.`;
  const limit=Number($('limit').value);$('warning').textContent=Number.isFinite(limit)&&data.boxes.length>limit?'Số người vượt mức dự kiến — hãy kiểm tra khung hình.':'';
};
$('file').onchange=()=>{const file=$('file').files[0];if(!file)return;reset();if(file.size>100*1024*1024){$('file').value='';status('Video vượt 100 MB của bản Free.');return;}url=URL.createObjectURL(file);video.src=url;$('start').disabled=false;status('Video chỉ được mở trên thiết bị này. Nhấn Phân tích.');};
video.onloadedmetadata=()=>{if(url&&Number.isFinite(video.duration)&&video.duration>120){reset();$('file').value='';status('Video vượt 2 phút của bản Free. Hãy chọn clip ngắn hơn.');}};
$('camera').onclick=async()=>{
  reset();const requestGeneration=generation;
  try{if(!navigator.mediaDevices?.getUserMedia)throw Error('Trình duyệt cần HTTPS và hỗ trợ camera.');const obtained=await navigator.mediaDevices.getUserMedia({video:true,audio:false});if(generation!==requestGeneration){obtained.getTracks().forEach(t=>t.stop());return;}stream=obtained;video.srcObject=stream;await video.play();$('start').disabled=false;$('stop').disabled=false;status('Camera đã mở. Nhấn Phân tích để bắt đầu AI.');}
  catch(error){stop();status('Không mở được camera: '+error.message);}
};
async function tick(runGeneration){
  if(!running||runGeneration!==generation)return;
  if(!video.paused&&!video.ended&&!busy&&video.readyState>=2){
    busy=true;submittedGeneration=generation;
    try{const frame=await createImageBitmap(video);if(!running||submittedGeneration!==generation){frame.close();busy=false;return;}canvas.width=frame.width;canvas.height=frame.height;ctx.drawImage(frame,0,0);worker.postMessage({type:'frame',frame},[frame]);}
    catch(error){busy=false;stop();status('Không đọc được video: '+error.message);}
  }
  if(running&&runGeneration===generation)setTimeout(()=>tick(runGeneration),effortInterval(effortSelect.value));
}
$('start').onclick=async()=>{if(running||!ready||(!url&&!stream))return;try{await video.play();generation++;running=true;$('start').disabled=true;$('stop').disabled=false;status('Đang phân tích trên thiết bị. Video không được tải lên.');tick(generation);}catch(error){status('Không phát được video: '+error.message);}};
$('stop').onclick=stop;
video.onended=()=>{running=false;$('start').disabled=false;status('Video đã kết thúc. Kết quả hiển thị là khung hình lấy mẫu gần nhất.');};
video.onerror=()=>{if(url){stop();status('Trình duyệt không đọc được định dạng video. Hãy thử MP4/H.264.');}};
worker.onerror=()=>{ready=false;stop();$('load').disabled=false;$('file').disabled=true;$('camera').disabled=true;status('Bộ chạy AI gặp lỗi. Tải lại trang để thử lại.');};
window.addEventListener('pagehide',()=>{stop();worker.terminate();if(url)URL.revokeObjectURL(url);});
