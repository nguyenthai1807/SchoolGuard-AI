'use strict';
const FE1_ONLY=false;
const PREVIEW_MODE=true;
const $=id=>document.getElementById(id),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const API={
 request(path,options={}){return PreviewAPI.request(path,options);},
 get(path){return this.request(path);},
 send(path,method,body){return this.request(path,{method,body:JSON.stringify(body)});}
};
let user=null,page='dashboard',cameraId=1,zonePoints=[],drawMode=false,selectedZone=[],frameUrl=null,detailUrl=null,offset=0,alertTotal=0,toastTimer,pollBusy=false,lastNew=null,viewGeneration=0,cameraActionBusy=false;
const statuses={new:'Mới',processing:'Đang xử lý',resolved:'Đã xử lý'},jobNames={idle:'Chưa chạy',ready:'Video sẵn sàng',starting:'Khởi động',loading:'Tải mô hình',running:'Đang phân tích',completed:'Hoàn tất',stopped:'Đã dừng',error:'Lỗi AI'};
function toast(text){$('toast').textContent=text;$('toast').classList.remove('hidden');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').classList.add('hidden'),4000)}
function pill(s){return '<span class="pill '+(s==='new'?'red':s==='processing'?'blue':'')+'">'+esc(statuses[s]||s)+'</span>'}
function alertTable(items){return '<div class="tablewrap"><table><thead><tr><th>Sự kiện</th><th>Camera</th><th>Thời điểm</th><th>Trạng thái</th><th></th></tr></thead><tbody>'+(items.length?items.map(a=>'<tr><td><b>'+esc(a.id)+'</b><br><small>Xâm nhập · video '+Number(a.video_seconds).toFixed(1)+'s</small></td><td>'+esc(a.camera_name)+'</td><td>'+esc(new Date(a.time).toLocaleString('vi-VN'))+'</td><td>'+pill(a.status)+'</td><td><button class="secondary" data-detail="'+esc(a.id)+'">Xem</button></td></tr>').join(''):'<tr><td colspan="5" class="muted">Chưa có cảnh báo phù hợp.</td></tr>')+'</tbody></table></div>'}
async function exit(call=true){if(call){try{await API.send('/auth/logout','POST',{});}catch(e){toast(e.message);return;}}user=null;viewGeneration++;$('detail').close();releaseImages();$('app').classList.add('hidden');$('login').classList.remove('hidden');$('password').value='';}
function releaseImages(){if(localPreviewURL){const v=$('localPreviewVideo');if(v){v.pause();v.removeAttribute('src');v.load();}URL.revokeObjectURL(localPreviewURL);localPreviewURL=null;}const video=$('smoothVideo');if(video){video.pause();video.removeAttribute('src');video.load();}if(frameUrl){URL.revokeObjectURL(frameUrl);frameUrl=null;}if(detailUrl){URL.revokeObjectURL(detailUrl);detailUrl=null;}}
async function enter(data){user=data.user;$('userLabel').textContent=user.name+' · '+(user.role==='admin'?'Admin':'Bảo vệ');$('login').classList.add('hidden');$('app').classList.remove('hidden');await navigate('dashboard');}
async function navigate(name){if(!['dashboard','camera','alerts','guide'].includes(name))return;page=name;offset=0;drawMode=false;releaseImages();const generation=++viewGeneration;document.querySelectorAll('[data-page]').forEach(b=>b.classList.toggle('active',b.dataset.page===page));$('pageTitle').textContent={dashboard:'Tổng quan an ninh',camera:'Giám sát camera',alerts:'Lịch sử cảnh báo',guide:'Cài đặt'}[page];$('content').innerHTML='<div class="panel">Đang tải dữ liệu…</div>';try{if(page==='dashboard')await dashboard(generation);else if(page==='guide')settings();else if(page==='camera')await camera(generation);else await alertPage(generation);}catch(e){if(generation!==viewGeneration)return;$('content').innerHTML='<div class="panel"><p class="error">'+esc(e.message)+'</p><button id="retry">Thử lại</button></div>';$('retry').onclick=()=>navigate(page)}}


async function dashboard(generation=viewGeneration){const s=await API.get('/dashboard/summary');if(generation!==viewGeneration||page!=='dashboard'||!user)return;$('content').innerHTML='<div class="row between"><p class="muted">'+s.today_alerts+' cảnh báo hôm nay (UTC).</p><button id="refresh" class="secondary">↻ Làm mới</button></div><div class="cards">'+[['Tổng cảnh báo',s.total_alerts,'Sự kiện được ghi nhận'],['Chưa xử lý',s.new_alerts,'Cần xác minh'],['Đã xử lý',s.resolved_alerts,'Hoàn thành'],['Camera đang chạy',s.active_cameras,'Đang phân tích']].map(([label,n,sub])=>'<div class="card"><small>'+label+'</small><div class="metric">'+n+'</div><small>'+sub+'</small></div>').join('')+'</div><div class="grid"><div class="panel"><div class="row between"><h2>Cảnh báo gần đây</h2><span class="pill blue">HOẠT ĐỘNG</span></div>'+alertTable(s.recent_alerts)+'</div><div class="panel"><h2>Tiến độ xử lý</h2>'+[['Mới',s.new_alerts],['Đang xử lý',s.processing_alerts],['Đã xử lý',s.resolved_alerts]].map(([label,n])=>'<div class="barrow"><span style="width:95px">'+label+'</span><div class="bar"><i style="width:'+(s.total_alerts?n/s.total_alerts*100:0)+'%"></i></div><b>'+n+'</b></div>').join('')+'</div></div><div class="panel"><h2>Camera trong khuôn viên</h2><div id="cameraSummary">Đang tải camera…</div></div>';$('refresh').onclick=()=>dashboard().catch(e=>toast(e.message));const cams=await API.get('/cameras');if(generation!==viewGeneration||page!=='dashboard')return;$('cameraSummary').innerHTML=cams.items.map(c=>'<div class="row between" style="padding:12px;border-bottom:1px solid var(--line)"><div><b>'+esc(c.name)+'</b><br><small>'+esc(c.location)+' · '+esc(c.original_name||'Chưa tải video')+'</small></div><span class="pill '+(c.runtime.status==='error'?'red':'blue')+'">'+esc(jobNames[c.runtime.status]||'Chưa chạy')+'</span></div>').join('');}
function settings(){$('content').innerHTML='<div class="settings-grid"><div class="panel"><div class="section-kicker">TÀI KHOẢN</div><h2>Bảo mật</h2><form id="changePassword"><label class="form-label" for="oldPassword">Mật khẩu hiện tại</label><input class="full" id="oldPassword" type="password" autocomplete="current-password" required><label class="form-label" for="newPassword">Mật khẩu mới</label><input class="full" id="newPassword" type="password" autocomplete="new-password" minlength="10" maxlength="128" required><button class="settings-save">Cập nhật mật khẩu</button><p id="passwordFeedback" class="muted" role="status"></p></form></div><div class="panel"><div class="section-kicker">CÁ NHÂN HÓA</div><h2>Giao diện</h2><p class="muted">Chọn giao diện phù hợp với không gian làm việc.</p><div class="theme-choices"><button type="button" data-set-theme="light" class="theme-choice"><span>☀</span>Sáng</button><button type="button" data-set-theme="dark" class="theme-choice"><span>☾</span>Tối</button></div></div></div>';applyTheme(document.documentElement.dataset.theme);$('changePassword').onsubmit=async e=>{e.preventDefault();const b=e.currentTarget.querySelector('button');b.disabled=true;try{await API.send('/auth/password','POST',{current_password:$('oldPassword').value,new_password:$('newPassword').value});await exit(false);toast('Đã đổi mật khẩu. Hãy đăng nhập lại.');}catch(err){toast(err.message);}finally{b.disabled=false;}};}

async function camera(){cameraPreview();}
async function alertPage(generation){$('content').innerHTML='<div class="panel"><div class="row between"><h2>Lịch sử cảnh báo</h2><span class="pill blue">SỰ KIỆN</span></div><div class="row toolbar"><input id="search" placeholder="Tìm mã cảnh báo" aria-label="Tìm mã"><select id="filter" aria-label="Trạng thái"><option value="">Tất cả trạng thái</option>'+Object.entries(statuses).map(([k,v])=>'<option value="'+k+'">'+v+'</option>').join('')+'</select><input id="dateFilter" type="date" aria-label="Ngày UTC"><button id="applyFilter" class="secondary">Lọc</button></div><div id="alertTable"></div><div class="row between" style="margin-top:18px"><small id="pageInfo"></small><div class="row"><button id="previous" class="secondary">← Trước</button><button id="next" class="secondary">Sau →</button></div></div></div>';for(const id of ['filter','dateFilter'])$(id).onchange=()=>{offset=0;loadAlerts().catch(e=>toast(e.message));};$('applyFilter').onclick=()=>{offset=0;loadAlerts().catch(e=>toast(e.message));};$('previous').onclick=()=>{offset=Math.max(0,offset-25);loadAlerts().catch(e=>toast(e.message));};$('next').onclick=()=>{offset+=25;loadAlerts().catch(e=>toast(e.message));};await loadAlerts(generation);}
async function loadAlerts(generation=viewGeneration){if(!$('search'))return;const query=new URLSearchParams({search:$('search').value,status:$('filter').value,date:$('dateFilter').value,offset,limit:25});const s=await API.get('/alerts?'+query);if(generation!==viewGeneration||!$('alertTable'))return;alertTotal=s.total;$('alertTable').innerHTML=alertTable(s.items);$('pageInfo').textContent=s.total?`${offset+1}–${offset+s.items.length} / ${s.total} cảnh báo`:'0 cảnh báo';$('previous').disabled=offset===0;$('next').disabled=offset+25>=s.total;}


async function detail(id){try{const a=await API.get('/alerts/'+encodeURIComponent(id));if(!user)return;$('detailBody').innerHTML='<span class="pill red">Xâm nhập khu vực cấm</span><h2 style="margin-top:15px">'+esc(a.id)+'</h2><p>'+esc(a.camera_name)+' · '+esc(new Date(a.time).toLocaleString('vi-VN'))+' · video '+a.video_seconds+'s</p><img id="evidence" alt="Ảnh sự kiện"><div class="row toolbar"><select id="detailStatus" aria-label="Trạng thái">'+Object.entries(statuses).map(([k,v])=>'<option value="'+k+'">'+v+'</option>').join('')+'</select><input id="detailNote" maxlength="2000" placeholder="Ghi chú xác minh" aria-label="Ghi chú"><button id="saveAlert">Lưu</button></div><small>'+esc(a.updated_by?'Cập nhật bởi '+a.updated_by:'Chưa có xác minh')+'</small>';$('detailStatus').value=a.status;$('detailNote').value=a.note;$('detail').showModal();const blob=await API.request('/alerts/'+encodeURIComponent(id)+'/image',{image:true});if(!$('detail').open||!user)return;if(detailUrl)URL.revokeObjectURL(detailUrl);detailUrl=URL.createObjectURL(blob);$('evidence').src=detailUrl;$('saveAlert').onclick=async()=>{const button=$('saveAlert');button.disabled=true;try{await API.send('/alerts/'+encodeURIComponent(id),'PATCH',{status:$('detailStatus').value,note:$('detailNote').value});$('detail').close();toast('Đã cập nhật cảnh báo');if(page==='dashboard')await dashboard();else if(!FE1_ONLY&&page==='alerts')await loadAlerts();}catch(e){toast(e.message);}finally{button.disabled=false;}};}catch(e){toast(e.message);}}

const previewPasswords={admin:'demo123',baove:'demo123'};
const previewAlerts=Array.from({length:7},(_,i)=>({id:'SG-'+(1028-i),camera_id:i%2+1,camera_name:i%2?'Camera 02':'Camera 01',time:new Date(Date.now()-i*7200000).toISOString(),video_seconds:3+i*4,status:i<3?'new':i<5?'processing':'resolved',note:'',updated_by:null}));
const previewCameras=[{id:1,name:'Camera 01',location:'Cổng trường',zone:[],runtime:{status:'idle'}},{id:2,name:'Camera 02',location:'Hành lang',zone:[],runtime:{status:'idle'}}];
const PreviewAPI={async request(path,options={}){
 const body=typeof options.body==='string'?JSON.parse(options.body):{};
 if(path==='/auth/me')throw Error('Chưa đăng nhập');
 if(path==='/auth/login'){
   if(!['admin','baove'].includes(body.username)||body.password!==previewPasswords[body.username])throw Error('Bản xem trước: admin hoặc baove / demo123.');
   return {user:{name:body.username==='admin'?'Khang':'Nhân viên bảo vệ',username:body.username,role:body.username==='admin'?'admin':'guard'}};
 }
 if(!user)throw Error('Vui lòng đăng nhập.');
 if(path==='/auth/logout')return {ok:true};
 if(path==='/auth/password'){
   if(body.current_password!==previewPasswords[user.username])throw Error('Mật khẩu hiện tại không đúng.');
   if(typeof body.new_password!=='string'||body.new_password.length<10||body.new_password.length>128)throw Error('Mật khẩu mới cần từ 10 đến 128 ký tự.');
   previewPasswords[user.username]=body.new_password;return {ok:true};
 }
 if(path==='/dashboard/summary'){const count=s=>previewAlerts.filter(a=>a.status===s).length;return {total_alerts:previewAlerts.length,new_alerts:count('new'),processing_alerts:count('processing'),resolved_alerts:count('resolved'),active_cameras:0,today_alerts:previewAlerts.filter(a=>a.time.slice(0,10)===new Date().toISOString().slice(0,10)).length,recent_alerts:structuredClone(previewAlerts.slice(0,5))};}
 if(path==='/cameras')return {items:structuredClone(previewCameras)};
 if(path.startsWith('/alerts?')){const q=new URLSearchParams(path.split('?')[1]);const a=previewAlerts.filter(a=>(!q.get('search')||a.id.toLowerCase().includes(q.get('search').toLowerCase()))&&(!q.get('status')||a.status===q.get('status'))&&(!q.get('date')||a.time.slice(0,10)===q.get('date')));const o=Number(q.get('offset')||0);return {items:structuredClone(a.slice(o,o+25)),total:a.length};}
 if(path.startsWith('/alerts/')){const a=previewAlerts.find(a=>a.id===decodeURIComponent(path.split('/')[2]));if(!a)throw Error('Không tìm thấy sự kiện.');if(path.endsWith('/image'))return new Blob(['<svg xmlns="http://www.w3.org/2000/svg" width="800" height="450"><rect width="800" height="450" fill="#102239"/><path d="M0 330L800 230V450H0" fill="#1b3e49"/><rect x="480" y="95" width="200" height="240" fill="#ed646422" stroke="#ed6464" stroke-width="3"/><text x="35" y="50" fill="#b2cbd2" font-family="sans-serif" font-size="20">SCHOOLGUARD • PREVIEW</text></svg>'],{type:'image/svg+xml'});if(options.method==='PATCH'){if(!Object.hasOwn(statuses,body.status))throw Error('Trạng thái không hợp lệ.');Object.assign(a,{status:body.status,note:String(body.note||''),updated_by:user.username});return {ok:true};}return structuredClone(a);}
 throw Error('Không tìm thấy chức năng.');
}};
let localPreviewURL=null;
function cameraPreview(){
 const cam=previewCameras.find(c=>c.id===cameraId)||previewCameras[0];
 $('content').innerHTML='<div class="grid"><div class="panel"><div class="row between"><h2>Camera theo dõi</h2><select id="localCameraSelect" aria-label="Chọn camera">'+previewCameras.map(c=>'<option value="'+c.id+'">'+esc(c.name+' · '+c.location)+'</option>').join('')+'</select></div><div class="stage"><video id="localPreviewVideo" controls playsinline></video><canvas id="localZoneCanvas" width="960" height="540" hidden aria-label="Chọn khu vực giám sát"></canvas><div id="localVideoEmpty" class="video-empty"><span>▣</span><p>Chưa có video</p></div></div><div class="row toolbar"><label class="upload-label" for="localVideoFile">＋ Chọn video</label><input id="localVideoFile" type="file" accept="video/*" hidden><span id="localVideoName" class="muted">'+esc(cam.name)+'</span></div></div><div><div class="panel"><div class="section-kicker">KHU VỰC GIÁM SÁT</div><h2>'+esc(cam.location)+'</h2><div class="row"><button id="localDraw" disabled>Vẽ vùng</button><button id="localSave" class="secondary" disabled>Lưu</button><button id="localCancel" class="secondary" disabled>Hủy</button></div><p id="localZoneInfo" class="muted" style="margin-top:16px">'+(cam.zone.length?cam.zone.length+' đỉnh':'Chưa thiết lập khu vực')+'</p><hr class="divider"><div class="row between"><small>Nguồn phát</small><span class="pill blue">VIDEO GỐC</span></div></div><div class="panel"><small>Trạng thái</small><p id="localPlaybackStatus" style="margin-top:10px;margin-bottom:0">Chưa có nguồn phát</p></div></div></div>';
 const video=$('localPreviewVideo'),canvas=$('localZoneCanvas'),ctx=canvas.getContext('2d');
 let points=structuredClone(cam.zone),editing=false;
 function paint(){
   ctx.clearRect(0,0,960,540);if(!video.videoWidth)return;
   const scale=Math.min(960/video.videoWidth,540/video.videoHeight),w=video.videoWidth*scale,h=video.videoHeight*scale,ox=(960-w)/2,oy=(540-h)/2;
   if(!points.length)return;ctx.beginPath();points.forEach(([x,y],i)=>i?ctx.lineTo(ox+x*w,oy+y*h):ctx.moveTo(ox+x*w,oy+y*h));if(points.length>2)ctx.closePath();ctx.fillStyle='#f15f7330';ctx.fill();ctx.strokeStyle='#f1808d';ctx.lineWidth=3;ctx.stroke();points.forEach(([x,y])=>{ctx.beginPath();ctx.arc(ox+x*w,oy+y*h,5,0,7);ctx.fillStyle='#fff';ctx.fill();});
 }
 function stopEditing(){editing=false;canvas.hidden=true;$('localSave').disabled=true;$('localCancel').disabled=true;$('localDraw').disabled=!video.videoWidth;}
 $('localCameraSelect').value=cameraId;
 $('localCameraSelect').onchange=e=>{cameraId=Number(e.target.value);navigate('camera');};
 $('localVideoFile').onchange=e=>{
   const file=e.target.files[0];if(!file)return;
   video.pause();video.removeAttribute('src');video.load();if(localPreviewURL)URL.revokeObjectURL(localPreviewURL);
   localPreviewURL=URL.createObjectURL(file);video.src=localPreviewURL;$('localVideoName').textContent=file.name;$('localVideoEmpty').hidden=true;stopEditing();
 };
 video.onloadedmetadata=()=>{$('localDraw').disabled=user.role!=='admin';$('localPlaybackStatus').textContent='Sẵn sàng • '+Math.round(video.duration||0)+' giây';};
 video.onplay=()=>{$('localPlaybackStatus').textContent='Đang phát';};
 video.onpause=()=>{$('localPlaybackStatus').textContent=video.ended?'Đã kết thúc':'Tạm dừng';};
 video.onerror=()=>{toast('Không mở được video. Hãy thử MP4 H.264.');$('localVideoEmpty').hidden=false;$('localDraw').disabled=true;};
 $('localDraw').onclick=()=>{video.pause();editing=true;points=[];canvas.hidden=false;canvas.style.pointerEvents='auto';$('localSave').disabled=true;$('localCancel').disabled=false;$('localDraw').disabled=true;paint();};
 canvas.onclick=e=>{
   if(!editing)return;const r=canvas.getBoundingClientRect(),scale=Math.min(r.width/video.videoWidth,r.height/video.videoHeight),w=video.videoWidth*scale,h=video.videoHeight*scale;
   const x=(e.clientX-r.left-(r.width-w)/2)/w,y=(e.clientY-r.top-(r.height-h)/2)/h;if(x<0||x>1||y<0||y>1)return;
   if(points.length>=20){toast('Khu vực có tối đa 20 đỉnh.');return;}
   points.push([x,y]);paint();$('localZoneInfo').textContent=points.length+' đỉnh';$('localSave').disabled=points.length<3;
 };
 $('localSave').onclick=()=>{
   const area=Math.abs(points.reduce((sum,p,i)=>{const n=points[(i+1)%points.length];return sum+p[0]*n[1]-n[0]*p[1];},0))/2;
   if(area<.001){toast('Khu vực chưa hợp lệ.');return;}
   cam.zone=structuredClone(points);stopEditing();$('localZoneInfo').textContent=cam.zone.length+' đỉnh • Đã lưu';toast('Đã lưu khu vực giám sát');
 };
 $('localCancel').onclick=()=>{points=structuredClone(cam.zone);stopEditing();$('localZoneInfo').textContent=points.length?points.length+' đỉnh':'Chưa thiết lập khu vực';};
}
function applyTheme(theme){
 document.documentElement.dataset.theme=theme;
 document.documentElement.style.colorScheme=theme;
 $('themeIcon').textContent=theme==='dark'?'☀':'☾';
 $('themeLabel').textContent=theme==='dark'?'Chế độ sáng':'Chế độ tối';
 $('themeToggle').setAttribute('aria-pressed',String(theme==='dark'));
 $('themeToggle').setAttribute('aria-label',theme==='dark'?'Chuyển sang chế độ sáng':'Chuyển sang chế độ tối');
 document.querySelectorAll('[data-set-theme]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.setTheme===theme)));
}
function saveTheme(theme){applyTheme(theme);try{localStorage.setItem('schoolguard-theme',theme);}catch{}}
let initialTheme=matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';
try{const stored=localStorage.getItem('schoolguard-theme');if(['light','dark'].includes(stored))initialTheme=stored;}catch{}
applyTheme(initialTheme);
$('themeToggle').onclick=()=>saveTheme(document.documentElement.dataset.theme==='dark'?'light':'dark');
document.addEventListener('click',e=>{const b=e.target.closest('[data-set-theme]');if(b)saveTheme(b.dataset.setTheme);});

$('content').onclick=e=>{const b=e.target.closest('[data-detail]');if(b)detail(b.dataset.detail)};$('closeDetail').onclick=()=>$('detail').close();$('logout').onclick=()=>exit();document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>navigate(b.dataset.page));$('edition').textContent='KHÔNG GIAN LÀM VIỆC';$('editionLogin').textContent='SchoolGuard AI • Campus Security';
$('loginForm').onsubmit=async e=>{e.preventDefault();const b=e.currentTarget.querySelector('button');b.disabled=true;$('loginError').textContent='';try{await enter(await API.send('/auth/login','POST',{username:$('username').value.trim(),password:$('password').value}));}catch(err){$('loginError').textContent=err.message;}finally{b.disabled=false;}};
function clock(){$('clock').textContent=new Date().toLocaleString('vi-VN')}clock();setInterval(clock,1000);

(async()=>{try{await enter(await API.get('/auth/me'));}catch{}})();
