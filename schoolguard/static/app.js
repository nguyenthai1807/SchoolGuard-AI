'use strict';
const $ = (s, root = document) => root.querySelector(s);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels = {completed:'Hoàn tất',running:'Đang xử lý',queued:'Đang chờ',failed:'Thất bại',cancelled:'Đã hủy',new:'Chưa duyệt',acknowledged:'Đã tiếp nhận',resolved:'Đã xử lý',false_positive:'Báo sai'};
const badge = s => `<span class="badge ${esc(s)}">${esc(labels[s] || s)}</span>`;
const fmt = n => Number(n || 0).toLocaleString('vi-VN', {maximumFractionDigits:2});
const poseFor = name => /^yolov(?:8|9|10)/.test(String(name)) ? 'yolov8n-pose' : String(name).startsWith('yolo26') ? 'yolo26n-pose' : 'yolo11n-pose';
function showModelCatalog(select, catalog, plan, preferred){
  const previous=select.value;
  select.replaceChildren();
  for(const item of catalog){
    const option=new Option(`${item.label} · ${item.tier==='free'?'Free':'Pro'}${item.available?'':' · chưa tải'}`,item.id);
    option.disabled=!item.available||(plan==='free'&&item.tier!=='free');
    select.add(option);
  }
  const available=[...select.options].filter(option=>!option.disabled);
  const selected=[previous,preferred].find(value=>available.some(option=>option.value===value));
  if(selected)select.value=selected;
  else if(available.length)select.value=available[0].value;
  select.disabled=!available.length;
}
const alertTrack = alert => {
  const value=Number(alert?.track_id);
  if(Number.isFinite(value)&&value>=0)return `#${fmt(value)}`;
  return ['fire','smoke'].includes(alert?.event_type)?'Không áp dụng':'Toàn cảnh';
};
let me, accountName='', timer, routeVersion=0, toastTimer, cameraStream=null, cameraSession=null, cameraTimer=null, cameraRemote=false;
let authRevision=0;
let notificationTimer=null, notificationVersion=0;
let previewTimer=null, previewRequest=null, previewUrl=null, cameraViewVersion=0;
const cameraSessionKey='lh25-camera-session';
window.addEventListener('pagehide',()=>{
  const session=cameraSession||sessionStorage.getItem(cameraSessionKey);
  if(session)navigator.sendBeacon('/api/live/'+encodeURIComponent(session)+'/stop');
  if(cameraStream)cameraStream.getTracks().forEach(track=>track.stop());
});
let selectedSource=null, polygon=[], zones=[], baseImage=null, sourceOffset=0;
let demoItems=[], demoCapabilities={};
async function api(path, options={}) {
  const response = await fetch('/api'+path, {credentials:'same-origin', ...options, headers:{...(options.body instanceof FormData ? {} : {'Content-Type':'application/json'}), ...options.headers}});
  if (!response.ok) {
    let detail; try { detail=(await response.json()).detail; } catch { detail=response.statusText; }
    // Startup /me can finish after a successful Google callback; its stale 401
    // must not hide the dashboard that has just opened.
    if(response.status===401 && path!='/login' && path!='/me') showLogin();
    const error=new Error(typeof detail==='string' ? detail : JSON.stringify(detail));error.status=response.status;throw error;
  }
  return response.json();
}
function toast(message) { $('#toast').textContent=message; $('#toast').hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('#toast').hidden=true,6000); }
function showLogin() { clearTimeout(timer); clearInterval(notificationTimer); notificationVersion++; $('#notification-panel').hidden=true; $('#notification-bell').setAttribute('aria-expanded','false'); stopCamera().catch(()=>{}); $('#login').hidden=false; $('#shell').hidden=true; me=null; }
async function loadNotifications(){
 const version=notificationVersion;
 const data=await api('/notifications');
 if(version!==notificationVersion||$('#shell').hidden)return;
 const count=$('#notification-count');count.hidden=!data.unread;count.textContent=data.unread>99?'99+':String(data.unread);
 $('#notification-bell').setAttribute('aria-label',data.unread?`Thông báo, ${data.unread} chưa đọc`:'Thông báo, không có tin chưa đọc');
 const list=$('#notification-list');
 list.innerHTML=data.items.length?data.items.map(item=>`<a class="notification-item ${item.read?'':'unread'}" href="${esc(item.href)}" data-notification-id="${esc(item.id)}"><strong>${esc(item.title)}</strong><small>${esc(item.message)}</small><span class="notification-time">${esc(new Date(item.created_at).toLocaleString('vi-VN'))}</span></a>`).join(''):'<p class="notification-empty">Chưa có thông báo. Khi Pro được kích hoạt hoặc video xử lý xong, bạn sẽ thấy tại đây.</p>';
 $('#notification-read-all').disabled=!data.unread;
}
const refreshNotifications=()=>loadNotifications().catch(error=>{if(error.status!==401)console.warn('Notifications:',error.message);});
$('#notification-bell').onclick=()=>{const panel=$('#notification-panel');panel.hidden=!panel.hidden;$('#notification-bell').setAttribute('aria-expanded',String(!panel.hidden));if(!panel.hidden)refreshNotifications();};
$('#notification-read-all').onclick=async()=>{try{await api('/notifications/read-all',{method:'POST'});await loadNotifications();}catch(error){toast(error.message);}};
$('#notification-list').addEventListener('click',async event=>{const link=event.target.closest('[data-notification-id]');if(!link)return;$('#notification-panel').hidden=true;$('#notification-bell').setAttribute('aria-expanded','false');try{await api('/notifications/'+encodeURIComponent(link.dataset.notificationId)+'/read',{method:'POST'});refreshNotifications();}catch(error){toast(error.message);}});
document.addEventListener('click',event=>{if(!event.target.closest('.notification-wrap')){$('#notification-panel').hidden=true;$('#notification-bell').setAttribute('aria-expanded','false');}});
document.addEventListener('keydown',event=>{if(event.key==='Escape'){$('#notification-panel').hidden=true;$('#notification-bell').setAttribute('aria-expanded','false');}});
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&!$('#shell').hidden)refreshNotifications();});
function updateAccountSummary(plan,profile){
 if(profile?.display_name)accountName=profile.display_name;
 const name=accountName||me.username;
 $('#identity').textContent=`${name} · ${me.role==='admin'?'Quản trị viên':plan.plan==='pro_local'?'Pro Local':'Free'}`;
 const label=plan.plan==='admin'?'ADMIN':plan.plan==='pro_local'?'PRO LOCAL':'FREE';
 const left=plan.video_limit===null?'':` · còn ${Math.max(0,plan.video_limit-plan.video_used)}/${plan.video_limit} video`;
 $('#account-summary').textContent=label+left;
}
function enter() { $('#login').hidden=true; $('#shell').hidden=false; $('#content').innerHTML='<div class="empty">Đang chuẩn bị bảng điều khiển…</div>'; notificationVersion++; clearInterval(notificationTimer); refreshNotifications(); notificationTimer=setInterval(()=>{if(!document.hidden)refreshNotifications();},15000); $('#identity').textContent=`${me.username} · ${me.role}`; trainingLink.style.display=me.role==='admin'?'':'none'; $('#admin-link').hidden=me.role!=='admin'; Promise.all([api('/profile'),api('/telegram/status'),api('/me/plan')]).then(([p,s,plan])=>{updateAccountSummary(plan,p);if(me.username!=='admin'&&(!p.email||!s.linked)){if(location.hash==='#telegram')renderRoute();else location.hash='#telegram';}else renderRoute();}).catch(()=>renderRoute()); }
window.addEventListener('lh25-google-authenticated',event=>{authRevision++;me=event.detail;if(!location.hash)history.replaceState(null,'','#overview');enter();});
$('#login-form').addEventListener('submit', async e => {e.preventDefault(); const f=new FormData(e.target); const b=$('button',e.target); b.disabled=true; try {me=await api('/login',{method:'POST',body:JSON.stringify(Object.fromEntries(f))}); $('#login-error').textContent=''; e.target.password.value=''; enter();} catch(error){$('#login-error').textContent=error.message;} finally{b.disabled=false;}});
$('#logout').onclick=async()=>{try{await api('/logout',{method:'POST'});showLogin();}catch(e){toast(e.message);}};
window.addEventListener('hashchange',()=>{if(me)renderRoute();});
const titles={overview:'Tổng quan',library:'Phân tích video',camera:'Webcam trực tiếp',jobs:'Tác vụ xử lý',alerts:'Cảnh báo',telegram:'Kết nối Telegram',plan:'Gói của tôi',system:'Hệ thống',job:'Chi tiết phân tích',training:'Huấn luyện & đánh giá'};
const trainingLink=document.createElement('a');trainingLink.href='#training';trainingLink.dataset.nav='training';trainingLink.textContent='Dữ liệu & đánh giá';document.querySelector('nav').insertBefore(trainingLink,document.querySelector('[data-nav="system"]'));
async function renderRoute(){
  if(location.hash.startsWith('#faces')){location.hash='#camera';return;}
  if((cameraStream||cameraRemote) && location.hash!=='#camera') await stopCamera();
  clearTimeout(timer); const version=++routeVersion; const [page='overview',id]=location.hash.slice(1).split('/');
  $('#page-title').textContent=titles[page]||'Tổng quan'; document.querySelectorAll('[data-nav]').forEach(a=>a.classList.toggle('active',a.dataset.nav===(page==='job'?'jobs':page)));
  $('#content').innerHTML='<div class="empty">Đang tải…</div>';
  try { if(page==='library') await library(); else if(page==='camera') await cameraPage(version); else if(page==='jobs') await jobsPage(version); else if(page==='job'&&id) await jobPage(id,version); else if(page==='alerts') await alertsPage(version); else if(page==='telegram') await telegramPage(version); else if(page==='plan') await planPage(version); else if(page==='system') { await systemPage(); await systemEnhancements(); } else if(page==='training') await trainingPage(version); else await overview(version); } catch(error){if(version===routeVersion)$('#content').innerHTML=`<div class="panel error">${esc(error.message)}</div>`;}
}
async function allFaces(query){
  let items=[],offset=0,total=0;
  do{const d=await api(`/faces?${query}&offset=${offset}&limit=500`);items.push(...d.items);total=d.total;offset+=d.items.length;if(!d.items.length)break;}while(offset<total);
  return {items,total};
}
function faceCards(items,live=false){
  if(!items.length)return '<div class="empty">Chưa nhận diện được khuôn mặt rõ trong khoảng này.</div>';
  return `<div class="face-grid">${items.map(f=>`<article class="face-card"><img loading="lazy" src="/api/faces/${encodeURIComponent(f.id)}/image" alt="Ảnh đại diện khuôn mặt ${f.ordinal}"><div class="face-card-info"><strong>Khuôn mặt ${f.ordinal}</strong><small>${live?`Lần đầu: ${esc(new Date(f.first_seen).toLocaleTimeString('vi-VN'))}`:`Xuất hiện từ ${fmt(f.video_time)}s`} · thấy ${fmt(f.seen_count)} lần</small>${live&&me.role!=="viewer"?`<button type="button" class="face-delete" data-delete-face="${esc(f.id)}" aria-label="Xóa khuôn mặt ${f.ordinal}">⌫ <span>Xóa</span></button>`:""}</div></article>`).join('')}</div>`;
}
function personCards(jobId, people){
  if(!people.available)return '<p class="help">Tác vụ cũ chưa lưu ảnh vùng đầu/vai. Hãy phân tích lại video để xem ảnh từng người được theo dõi.</p>';
  if(!people.items.length)return '<div class="empty">Chưa có người nào được gán mã theo dõi trong video.</div>';
  return `<div class="face-grid">${people.items.map(p=>`<article class="face-card">${p.image?`<img loading="lazy" src="/api/jobs/${encodeURIComponent(jobId)}/people/${p.track_id}/image" alt="Ảnh vùng đầu và vai của track ${p.track_id}">`:'<div class="empty">Không có ảnh rõ</div>'}<div><strong>Người theo dõi #${fmt(p.track_id)}</strong><small>Từ ${fmt(p.first_seen)}s · thấy ${fmt(p.seen_count)} frame</small></div></article>`).join('')}</div>${people.truncated?'<p class="help">Đã đạt giới hạn lưu 500 track; danh sách này chưa đầy đủ.</p>':''}`;
}
async function cameraFaceHistory(day,version){
  const today=new Date(), localDay=`${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;
  const selected=day||localDay;
  const [days,faces]=await Promise.all([api('/faces/days'),allFaces('day='+encodeURIComponent(selected))]);
  if(version!==routeVersion||!$('#camera-history'))return;
  $('#camera-history').innerHTML=`<div class="face-history"><section class="panel"><h2>Ngày ghi nhận từ webcam</h2><button class="face-day ${selected===localDay?'active':''}" data-face-day="${localDay}">Hôm nay · ${localDay}</button>${days.items.filter(d=>d.day!==localDay).map(d=>`<button class="face-day ${selected===d.day?'active':''}" data-face-day="${esc(d.day)}"><span>${esc(d.day)}</span><strong>${fmt(d.count)}</strong></button>`).join('')}<p class="help">Mỗi ngày có số khuôn mặt riêng. Ảnh và dữ liệu chỉ lưu tại máy này.</p></section><section class="panel"><div class="panel-head"><h2>${esc(selected)} · ${fmt(faces.total)} khuôn mặt ước tính</h2><div class="face-tools"><span class="tag">WEBCAM</span>${me.role!=="viewer"?`<button type="button" class="face-reset" data-delete-day="${esc(selected)}" ${faces.total?"":"disabled"}>↺ Xóa cả ngày</button>`:""}</div></div><p class="help">Xóa dữ liệu cũ để thử lượt nhận diện mới. Camera sẽ dừng trước khi xóa.</p>${faceCards(faces.items,true)}<p class="help">Mặt quá nhỏ, mờ hoặc bị che có thể không được nhận ra; một người đôi khi bị đếm trùng.</p></section></div>`;
  document.querySelectorAll('[data-face-day]').forEach(button=>button.onclick=()=>cameraFaceHistory(button.dataset.faceDay,version).catch(e=>toast(e.message)));
  if(selected===localDay){
    if($('#camera-face-count'))$('#camera-face-count').textContent=faces.total;
    if($('#camera-faces'))$('#camera-faces').innerHTML=faceCards(faces.items,true);
  }
}
function jobTable(rows){return rows.length?`<div class="table-wrap"><table><thead><tr><th>VIDEO / CAMERA</th><th>TRẠNG THÁI</th><th>TIẾN ĐỘ</th><th>CẢNH BÁO</th><th>THỜI ĐIỂM</th></tr></thead><tbody>${rows.map(j=>`<tr><td><a href="#job/${j.id}">${esc(j.source_name)}</a><br><small>${esc(j.config.camera_name)}</small></td><td>${badge(j.status)}</td><td>${Math.round(j.progress*100)}% · ${fmt(j.frames)} frame</td><td>${j.events}</td><td>${esc(new Date(j.created_at).toLocaleString('vi-VN'))}</td></tr>`).join('')}</tbody></table></div>`:'<div class="empty">Chưa có tác vụ. Mở thư viện và chọn một video để bắt đầu.</div>';}
async function overview(version){
 const d=await api('/stats');if(version!==routeVersion)return; const count=(rows,s)=>rows.find(x=>x.status===s)?.count||0;
 $('#content').innerHTML=`<div class="grid metrics"><div class="metric"><span>Nguồn video / chuỗi ảnh</span><strong>${d.sources}</strong></div><div class="metric"><span>Phân tích hoàn tất</span><strong>${count(d.jobs,'completed')}</strong></div><div class="metric"><span>Đang chờ / xử lý</span><strong>${count(d.jobs,'queued')+count(d.jobs,'running')}</strong></div><div class="metric"><span>Cảnh báo cần duyệt</span><strong>${count(d.alerts,'new')}</strong></div></div><div class="panel"><div class="panel-head"><h2>Hoạt động gần đây</h2><div class="actions"><a href="#library">+ Phân tích video</a><a href="#camera">Mở webcam ↗</a></div></div>${jobTable(d.latest)}</div><div class="notice">AI có thể báo sai hoặc bỏ sót. Hãy xem ảnh/video bằng chứng; LH25 không thay thế thiết bị báo cháy hay chăm sóc khẩn cấp.</div>`;
 timer=setTimeout(()=>overview(version).catch(e=>toast(e.message)),3000);
}
async function library(){
 selectedSource=null;polygon=[];zones=[];
 const currentPlan=await api('/me/plan');
 $('#content').innerHTML=`<div class="two-col"><section class="panel"><div class="panel-head"><h2>${me.role==='admin'?'Thư viện dữ liệu':'Video của bạn'}</h2><span id="source-count" class="tag"></span></div><div class="toolbar"><input id="search" aria-label="Tìm video" placeholder="Tìm theo tên video…"><select id="split" aria-label="Tập dữ liệu">${me.role==='admin'?'<option value="">Tất cả</option><option value="training">Training · video</option><option value="testing">Testing · chuỗi ảnh</option><option value="uploaded">Đã tải lên</option><option value="research">Dữ liệu nghiên cứu sự kiện</option>':'<option value="uploaded">Video đã tải lên của bạn</option>'}</select></div><div id="sources" class="source-list"></div><div class="pagination"><button id="prev" class="quiet">Trước</button><span id="page-number"></span><button id="next" class="quiet">Sau</button></div><hr><label>Tải video của bạn (tối đa ${Math.round((currentPlan?.upload_bytes||1073741824)/1048576)} MB)<input id="upload" type="file" accept=".mp4,.avi,.mov,.mkv"></label><p class="help">Video gốc được giữ trên máy chạy LH25. Chỉ bạn và quản trị viên có quyền truy cập kết quả của tài khoản này.</p></section><section id="configure" class="panel"><div class="empty">Chọn video bên trái để xem ảnh đầu tiên,<br>vẽ vùng hạn chế và cấu hình phân tích.</div></section></div>`;
 if(currentPlan.video_limit!==null)$('#content').insertAdjacentHTML('afterbegin',`<div class="notice">${currentPlan.plan==='free'?'Free':'Pro Local'}: ${currentPlan.video_used} / ${currentPlan.video_limit} video tháng này; tối đa ${Math.round(currentPlan.video_seconds/60)} phút và ${Math.round(currentPlan.upload_bytes/1048576)} MB/video. <a href="#plan">Xem gói và lượt dùng</a>.</div>`);
 if(me.role==='admin'){
  $('#content').insertAdjacentHTML('afterbegin',`<section class="panel demo-library" aria-labelledby="demo-title"><div class="panel-head"><div><h2 id="demo-title">★ Video demo đã duyệt</h2><p class="help">Tối đa 5 video độc lập cho mỗi chức năng. Sao chỉ xác nhận một trường hợp đã xem thủ công; không phải tỷ lệ chính xác của model.</p></div><span class="tag">CHỈ ADMIN</span></div><div id="demo-groups" class="demo-groups"><p class="muted">Đang tải demo…</p></div><form id="demo-form" class="demo-form" hidden><h3 id="demo-selection">Đánh dấu video demo</h3><div class="form-grid"><label>Chức năng<select name="capability" required></select></label><label>Tác vụ làm bằng chứng<select name="evidence_job_id" required></select></label></div><label>Cơ sở được phép trình chiếu / thương mại<input name="rights_note" minlength="8" maxlength="300" required placeholder="Ví dụ: video nhóm tự quay và đã có đồng ý"></label><label>Ghi chú kiểm chứng thủ công<input name="review_note" minlength="15" maxlength="500" required placeholder="Đã xem video gốc, timestamp và cảnh báo nào đúng?"></label><label class="check"><input name="review_confirmed" type="checkbox" required> Tôi đã xem lại clip gốc, ảnh/video kết quả và kiểm tra quyền sử dụng.</label><div class="actions"><button type="submit">★ Lưu demo</button><button id="demo-cancel" type="button" class="quiet">Hủy</button></div><p class="help">Không gắn sao clip nghiên cứu hạn chế quyền, clip báo nhầm hoặc clip chỉ có cảnh báo AI chưa kiểm chứng.</p></form></section>`);
  $('#demo-form .actions').insertAdjacentHTML('beforebegin','<label class="check"><input name="academic_only" type="checkbox"> Chỉ dùng demo học thuật nội bộ · không dùng trong STORE hoặc quảng cáo.</label>');
  $('#demo-cancel').onclick=()=>{$('#demo-form').hidden=true;};
  $('#demo-form').onsubmit=saveDemoVideo;
  await refreshDemoVideos();
 }
 let delay;$('#search').oninput=()=>{clearTimeout(delay);delay=setTimeout(()=>{sourceOffset=0;loadSources().catch(e=>toast(e.message));},250);}; $('#split').onchange=()=>{sourceOffset=0;loadSources().catch(e=>toast(e.message));};$('#prev').onclick=()=>{sourceOffset=Math.max(0,sourceOffset-40);loadSources().catch(e=>toast(e.message));};$('#next').onclick=()=>{sourceOffset+=40;loadSources().catch(e=>toast(e.message));};
 $('#upload').onchange=async e=>{const f=e.target.files[0];if(!f)return;const form=new FormData();form.append('file',f);e.target.disabled=true;try{const result=await api('/sources/upload',{method:'POST',body:form});toast('Đã thêm video.');await loadSources();await selectSource(result.id);}catch(error){toast(error.message);}finally{e.target.disabled=false;}};
 sourceOffset=0;await loadSources();
}
async function loadSources(){
 const q=$('#search')?.value||'',split=$('#split')?.value||'';
 const data=await api(`/sources?q=${encodeURIComponent(q)}&split=${split}&offset=${sourceOffset}`);
 if(!$('#sources'))return;
 $('#source-count').textContent=`${data.total} nguồn`;
 $('#sources').innerHTML=data.items.map(s=>`<div class="source-row ${selectedSource?.id===s.id?'selected':''}"><div><strong>${esc(s.name)}</strong><small>${esc(s.split)} · ${s.kind==='frames'?'chuỗi JPG':'video'}${me.role==='admin'&&demoItems.some(d=>d.source_id===s.id)?' · ★ demo':''}</small></div><div class="source-row-actions">${me.role==='admin'&&s.kind==='video'?`<button class="quiet demo-star-action" type="button" data-demo-source="${esc(s.id)}" aria-label="Đánh dấu demo cho ${esc(s.name)}">☆</button>`:''}<button class="quiet" data-source="${esc(s.id)}">Chọn</button></div></div>`).join('')||'<div class="empty">Không có video phù hợp.</div>';
 $('#page-number').textContent=`${data.total?sourceOffset+1:0}–${Math.min(sourceOffset+40,data.total)} / ${data.total}`;
 $('#prev').disabled=sourceOffset===0;$('#next').disabled=sourceOffset+40>=data.total;
 document.querySelectorAll('[data-source]').forEach(b=>b.onclick=()=>selectSource(b.dataset.source).catch(e=>toast(e.message)));
 document.querySelectorAll('[data-demo-source]').forEach(b=>b.onclick=()=>openDemoForm(b.dataset.demoSource).catch(e=>toast(e.message)));
}
async function refreshDemoVideos(){
 const data=await api('/admin/demo-videos');demoItems=data.items;demoCapabilities=data.capabilities;
 if(!$('#demo-groups'))return;
 const emptyNotes={interaction:'Quy tắc chuyển động mạnh cũng có thể báo trên clip không xung đột. Cần xem toàn video và mốc cảnh báo trước khi gắn sao.'};
 $('#demo-groups').innerHTML=Object.entries(demoCapabilities).map(([key,label])=>{const items=demoItems.filter(d=>d.capability===key);return `<section class="demo-group" aria-label="${esc(label)}"><div class="demo-group-head"><strong>${esc(label)}</strong><span>${items.length}/5 đã duyệt</span></div><div class="demo-cards">${items.map(d=>`<article class="demo-card"><a class="demo-card-link" href="#job/${encodeURIComponent(d.evidence_job_id)}" aria-label="Mở phân tích đã duyệt của ${esc(d.name)}"><img src="${esc(d.evidence_image||`/api/sources/${encodeURIComponent(d.source_id)}/thumbnail`)}" alt="" loading="lazy"><span class="demo-card-copy"><strong>${esc(d.name)}</strong>${d.academic_only?'<span class="demo-academic">Chỉ trình chiếu học thuật nội bộ</span>':''}<small>${d.available?'Video gốc sẵn sàng':'Video gốc đã chuyển/xóa'} · ${esc(d.review_note)}</small><span class="demo-open-cue">Xem phân tích đã duyệt →</span></span></a><div class="demo-card-footer"><small>Quyền dùng: ${esc(d.rights_note)}</small><div class="actions"><button class="quiet" data-demo-open="${esc(d.source_id)}" type="button">Cấu hình lại</button><button class="quiet" data-demo-remove="${esc(d.source_id)}" data-demo-capability="${esc(key)}" type="button" aria-label="Bỏ sao ${esc(d.name)}">Bỏ sao</button></div></div></article>`).join('')||`<p class="demo-empty">${esc(emptyNotes[key]||'Chưa có clip đã kiểm chứng. Cần xem video gốc và kết quả trước khi gắn sao.')}</p>`}</div></section>`;}).join('');
 document.querySelectorAll('[data-demo-open]').forEach(b=>b.onclick=()=>selectSource(b.dataset.demoOpen).catch(e=>toast(e.message)));
 document.querySelectorAll('[data-demo-remove]').forEach(b=>b.onclick=async()=>{if(!confirm('Bỏ sao demo này? Video và kết quả phân tích vẫn được giữ.'))return;try{await api(`/admin/demo-videos/${encodeURIComponent(b.dataset.demoCapability)}/${encodeURIComponent(b.dataset.demoRemove)}`,{method:'DELETE'});await refreshDemoVideos();await loadSources();}catch(e){toast(e.message);}});
}
async function openDemoForm(sourceId){
 const detail=await api('/sources/'+encodeURIComponent(sourceId));
 const jobs=await api('/admin/demo-videos/jobs/'+encodeURIComponent(sourceId));
 const form=$('#demo-form');form.hidden=false;form.dataset.sourceId=sourceId;form.reset();
 $('#demo-selection').textContent=`☆ Đánh dấu ${detail.name}`;
 form.elements.capability.innerHTML=Object.entries(demoCapabilities).map(([key,label])=>`<option value="${esc(key)}">${esc(label)}</option>`).join('');
 form.elements.evidence_job_id.innerHTML=jobs.items.map(j=>`<option value="${esc(j.id)}">${esc(j.finished_at||j.id)} · ${esc(j.events.map(e=>`${e.event_type}: ${e.count}`).join(', ')||'chưa có cảnh báo')} · ${j.faces} mặt</option>`).join('')||'<option value="">Chưa có tác vụ hoàn tất</option>';
 form.querySelector('button[type="submit"]').disabled=!jobs.items.length;
 form.scrollIntoView({behavior:'smooth',block:'center'});
}
async function saveDemoVideo(event){
 event.preventDefault();const form=event.currentTarget;const data=Object.fromEntries(new FormData(form));
 data.source_id=form.dataset.sourceId;data.review_confirmed=form.elements.review_confirmed.checked;data.academic_only=form.elements.academic_only.checked;
 const submit=form.querySelector('button[type="submit"]');submit.disabled=true;
 try{await api('/admin/demo-videos',{method:'POST',body:JSON.stringify(data)});form.hidden=true;await refreshDemoVideos();await loadSources();toast('Đã gắn sao demo sau khi lưu kiểm chứng.');}
 catch(e){toast(e.message);}finally{submit.disabled=false;}
}
async function selectSource(id){
 const [d,plan]=await Promise.all([api('/sources/'+id),api('/me/plan')]);selectedSource=d;polygon=[];zones=[];
 $('#configure').innerHTML=`<div class="panel-head"><h2>${esc(d.name)}</h2><span class="tag">${d.width} × ${d.height}</span></div><div class="canvas-wrap"><canvas id="zone-canvas" width="${d.width}" height="${d.height}" aria-label="Vẽ vùng cấm bằng cách nhấp các đỉnh trên ảnh"></canvas></div><p class="help">Nhấp ≥ 3 điểm để vẽ đa giác, sau đó lưu vùng. Không vẽ vùng = theo dõi toàn khung; các quy tắc tư thế vẫn hoạt động nếu bật.</p><div class="actions"><button id="save-zone" class="quiet" type="button">Lưu vùng</button><button id="undo" class="quiet" type="button">Lùi một điểm</button><button id="clear-points" class="quiet" type="button">Xóa nét vẽ</button></div><div id="zones" class="zones"></div><form id="job-form"><label>Tên camera<input name="camera_name" value="Campus / ${esc(d.name)}" maxlength="80" required></label><div class="form-grid"><label>Model<select name="model"><option value="yolo11s">YOLO11s · chi tiết hơn</option><option value="yolo11n">YOLO11n · nhẹ hơn</option><option value="yolo11n-pose">YOLO11n Pose · khung xương / hành vi</option></select></label><label>Kích thước suy luận<select name="image_size"><option value="640">640 px</option><option value="960">960 px · người ở xa</option></select></label><label>Ngưỡng tin cậy<input name="confidence" type="number" step="0.05" min="0.1" max="0.95" value="0.35" required></label><label>Thời gian trong vùng (giây)<input name="dwell_seconds" type="number" step="0.1" min="0" max="60" value="1.5" required></label><label>Phân tích bao nhiêu giây? (0 = toàn bộ)<input name="max_seconds" type="number" min="0" max="3600" value="30" required></label><label>Khoảng cách frame suy luận<select name="stride"><option value="1">1 · mọi frame (khuyến nghị)</option><option value="2">2 · bỏ qua 1 frame</option><option value="3">3 · bỏ qua 2 frame</option></select></label><label ${d.kind!=='frames'?'hidden':''}>FPS của chuỗi JPG<input name="sequence_fps" type="number" value="25" min="1" max="120" required></label></div>${d.fps_assumed?'<div class="notice">Chuỗi JPG không có timestamp. 25 FPS là giả định; thay bằng FPS gốc để đo thời gian lưu trú đúng.</div>':`<p class="help">Video: ${fmt(d.duration)} giây · ${fmt(d.fps)} FPS · ${fmt(d.frames)} frame. Dùng video FPS cố định để đo thời gian.</p>`}<label class="check"><input name="redact" type="checkbox">Che mờ người được phát hiện trong kết quả</label><button id="start-job" type="submit" ${me.role==='viewer'?'disabled':''}>Bắt đầu phân tích</button></form>`;
 $('#job-form [name="model"]').insertAdjacentHTML('beforeend','<option value="yolo26n">YOLO26n · thử nghiệm</option><option value="yolo26s">YOLO26s · thử nghiệm</option><option value="yolo26n-pose">YOLO26n Pose · thử nghiệm</option>');
 const advanced=document.createElement('fieldset');
 const effortField=document.createElement('fieldset');
 effortField.innerHTML=`<legend>Mức phân tích video</legend><label>Effort<select name="effort"><option value="low">Low · 640 px, lấy 1/5 frame</option><option value="medium">Medium · 640 px, lấy 1/3 frame</option><option value="high">High · 640 px, mọi frame ${plan.plan==='free'?'· Pro':''}</option><option value="extra">Extra · 960 px, lấy 1/2 frame ${plan.plan==='free'?'· Pro':''}</option><option value="extra_max">Extra Max · 960 px, mọi frame ${plan.plan==='free'?'· Pro':''}</option></select></label><p class="help">Mức cao xử lý nhiều frame hoặc ảnh lớn hơn nên chậm hơn và tốn tài nguyên hơn. Không bảo đảm chính xác hơn trong mọi video; hãy kiểm tra bằng chứng.</p>`;
 $('#job-form').insertBefore(effortField,$('#start-job'));
 const effortSelect=effortField.querySelector('select');
 for(const option of effortSelect.options)if(plan.plan==='free'&&['high','extra','extra_max'].includes(option.value))option.disabled=true;
 effortSelect.value='medium';
 const effortPresets={low:[640,5],medium:[640,3],high:[640,1],extra:[960,2],extra_max:[960,1]};
 for(const value of [4,5])$('#job-form [name="stride"]').add(new Option(`${value} · lấy 1/${value} frame`,String(value)));
 effortSelect.onchange=()=>{const [size,stride]=effortPresets[effortSelect.value];$('#job-form [name="image_size"]').value=String(size);$('#job-form [name="stride"]').value=String(stride);};
 effortSelect.onchange();
 advanced.innerHTML='<legend>Phát hiện mở rộng</legend><label class="check"><input type="checkbox" name="detect_falls">Nghi té ngã / nằm lâu (cần model Pose)</label><label class="check"><input type="checkbox" name="detect_interactions">Nghi xung đột qua chuyển động mạnh (cần Pose)</label><label class="check"><input type="checkbox" name="detect_fire" id="fire-toggle" disabled>Nghi lửa / khói (model riêng)</label><p id="fire-status" class="help">Đang kiểm tra model lửa / khói…</p><div class="form-grid"><label>Nằm lâu (giây)<input type="number" name="lying_seconds" value="8" min="2" max="120" required></label><label>Ngưỡng đông người (0 = tắt)<input type="number" name="crowd_threshold" value="0" min="0" max="200" required></label><label>Duy trì đông người (giây)<input type="number" name="crowd_seconds" value="3" min="1" max="60" required></label><label>Lưu trú lâu trong vùng (giây, 0 = tắt)<input type="number" name="loiter_seconds" value="0" min="0" max="3600" required></label></div><p class="notice">Các cảnh báo hành vi là thử nghiệm, cần người kiểm tra bằng chứng; không chẩn đoán ngất xỉu, ý định hay kết luận bạo lực. Bộ đếm là số người đang thấy. Cháy/khói không thay thế thiết bị báo cháy.</p>';
 $('#job-form').insertBefore(advanced,$('#start-job'));
 if(plan.plan==='free')advanced.querySelector('[name="detect_interactions"]').disabled=true;
 advanced.querySelector('legend').textContent='Phát hiện mở rộng';
 const home=document.createElement('fieldset');
 home.innerHTML='<legend>Thiết lập an toàn trong nhà</legend><label>Số người thường có trong nhà (n)<input type="number" name="expected_people" min="0" max="20" value="1" required></label><p class="help">Cảnh báo khi số người đang thấy lớn hơn n trong ít nhất 3 giây. Đây là đếm ẩn danh, không xác định ai là người lạ.</p>';
 $('#job-form').insertBefore(home,advanced);
 const faceField=document.createElement('fieldset');
 faceField.innerHTML='<legend>Khuôn mặt xuất hiện</legend><label class="check"><input id="face-toggle" name="recognize_faces" type="checkbox" disabled> Lưu ảnh đại diện và gom khuôn mặt trùng nhau trong video</label><p id="face-status" class="help">Đang kiểm tra model khuôn mặt…</p><p class="help">Ảnh và đặc trưng nhận dạng lưu cục bộ. Một khuôn mặt có thể bị tách thành nhiều mục khi góc nhìn thay đổi. Không gửi ảnh khuôn mặt này qua Telegram.</p>';
 $('#job-form').insertBefore(faceField,advanced);
 $('#job-form [name="camera_name"]').value=`Nhà / ${d.name}`.slice(0,80);
 $('#job-form [name="model"]').value=plan.plan==='free'?'yolov8n-pose':'yolo11n-pose';
 $('#job-form [name="detect_falls"]').checked=true;
 $('#job-form [name="max_seconds"]').value='0';
 for(const name of ['detect_falls','detect_interactions'])$('#job-form [name="'+name+'"]').onchange=e=>{if(e.target.checked){const model=$('#job-form [name="model"]');if(!model.value.endsWith('-pose')){model.value=poseFor(model.value);toast('Cảnh báo tư thế cần model Pose; đã chuyển sang '+model.value+'.');}}};
 $('#job-form [name="model"]').onchange=e=>{if(!e.target.value.endsWith('-pose')){const enabled=['detect_falls','detect_interactions'].filter(name=>$('#job-form [name="'+name+'"]').checked);for(const name of enabled)$('#job-form [name="'+name+'"]').checked=false;if(enabled.length)toast('Đã giữ model '+e.target.value+' và tắt cảnh báo tư thế vì model này không xuất Pose.');}};
 $('#job-form [name="redact"]').onchange=e=>{if(e.target.checked)$('#face-toggle').checked=false;};
 $('#face-toggle').onchange=e=>{if(e.target.checked)$('#job-form [name="redact"]').checked=false;};
 api('/system').then(s=>{if(!$('#fire-toggle'))return;$('#fire-toggle').disabled=!s.fire_available||plan.plan==='free';$('#fire-toggle').checked=s.fire_available&&plan.plan!=='free';$('#fire-status').textContent=plan.plan==='free'?'Nghi lửa / khói thuộc Pro Local.':s.fire_available?'Model lửa / khói sẵn sàng — chế độ thử nghiệm.':'Chưa có model lửa / khói; tính năng bị khóa, không giả lập kết quả.';$('#face-toggle').disabled=!s.face_available||!plan.faces;$('#face-toggle').checked=s.face_available&&plan.faces;$('#face-status').textContent=!plan.faces?'Lưu thư viện khuôn mặt thuộc Pro Local. Mở mục Gói của tôi để nâng cấp.':s.face_available?'Model khuôn mặt sẵn sàng. Chọn Che mờ người sẽ tắt lưu khuôn mặt.':'Chưa có model; chạy python -m scripts.download_face_models và khởi động lại LH25.';}).catch(e=>toast(e.message));
 api('/system').then(s=>{if(selectedSource?.id!==id)return;const select=$('#job-form [name="model"]');showModelCatalog(select,s.model_catalog,plan.plan,plan.plan==='free'?'yolov8n-pose':'yolo11n-pose');if([...select.options].some(o=>o.value===(plan.plan==='free'?'yolov8n-pose':'yolo11n-pose')&&!o.disabled))select.value=plan.plan==='free'?'yolov8n-pose':'yolo11n-pose';}).catch(()=>{});
 baseImage=new Image();baseImage.onload=redraw;baseImage.src=`/api/sources/${id}/thumbnail`;
 $('#zone-canvas').onclick=e=>{const r=e.target.getBoundingClientRect();if(polygon.length>=30){toast('Tối đa 30 điểm.');return;}polygon.push([Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))]);redraw();};
 $('#undo').onclick=()=>{polygon.pop();redraw();};$('#clear-points').onclick=()=>{polygon=[];redraw();};$('#save-zone').onclick=()=>{if(polygon.length<3){toast('Cần ít nhất 3 điểm.');return;}if(zones.length>=8){toast('Tối đa 8 vùng.');return;}zones.push({name:`Vùng hạn chế ${zones.length+1}`,points:[...polygon]});polygon=[];renderZones();redraw();};
 $('#job-form').onsubmit=async e=>{e.preventDefault();if(polygon.length){toast('Hãy lưu hoặc xóa nét vẽ hiện tại trước khi chạy.');return;}const f=new FormData(e.target);const data=Object.fromEntries(f);for(const k of ['image_size','confidence','dwell_seconds','max_seconds','stride','sequence_fps','lying_seconds','crowd_seconds','expected_people','loiter_seconds'])data[k]=Number(data[k]);for(const k of ['redact','detect_falls','detect_interactions','detect_fire','recognize_faces'])data[k]=f.has(k);data.source_id=id;data.zones=zones;const b=$('#start-job');b.disabled=true;try{const j=await api('/jobs',{method:'POST',body:JSON.stringify(data)});location.hash='#job/'+j.id;}catch(error){toast(error.message);b.disabled=false;}};
 await loadSources();
}
function renderZones(){$('#zones').innerHTML=zones.map((z,i)=>`<span class="zone-chip">${esc(z.name)} <button type="button" data-delete-zone="${i}" aria-label="Xóa ${esc(z.name)}">×</button></span>`).join('');document.querySelectorAll('[data-delete-zone]').forEach(b=>b.onclick=()=>{zones.splice(Number(b.dataset.deleteZone),1);renderZones();redraw();});}
function redraw(){const canvas=$('#zone-canvas');if(!canvas||!baseImage?.complete)return;const ctx=canvas.getContext('2d');ctx.drawImage(baseImage,0,0,canvas.width,canvas.height);for(const [pts,saved] of [...zones.map(z=>[z.points,true]),[polygon,false]]){if(!pts.length)continue;ctx.beginPath();pts.forEach(([x,y],i)=>i?ctx.lineTo(x*canvas.width,y*canvas.height):ctx.moveTo(x*canvas.width,y*canvas.height));if(saved)ctx.closePath();ctx.strokeStyle=saved?'#54c7ff':'#ffdc80';ctx.lineWidth=3;ctx.stroke();if(saved){ctx.fillStyle='#36b7ff28';ctx.fill();}for(const [x,y]of pts){ctx.beginPath();ctx.arc(x*canvas.width,y*canvas.height,4,0,Math.PI*2);ctx.fillStyle='#ffdc80';ctx.fill();}}}
async function jobsPage(version){const d=await api('/jobs');if(version!==routeVersion)return;$('#content').innerHTML=`<section class="panel"><div class="panel-head"><h2>Lịch sử phân tích</h2><a href="#library">+ Phân tích video</a></div>${jobTable(d.items)}<p class="help">Hiển thị ${d.items.length} / ${d.total} tác vụ gần nhất.</p></section>`;timer=setTimeout(()=>jobsPage(version).catch(e=>toast(e.message)),2000);}
async function jobPage(id,version){
 $('#content').innerHTML=`<div id="job-alarm" class="red-alarm" role="alert" hidden></div><div class="job-layout"><section class="panel"><div class="panel-head"><h2 id="job-name">Đang tải…</h2><span id="job-badge"></span></div><div id="player"><img id="live-preview" class="preview" alt="Ảnh kết quả xử lý gần nhất" hidden><div id="preview-wait" class="empty">Đang chờ frame đầu tiên…</div></div><div id="event-timeline" class="timeline"></div><div id="job-progress"></div></section><section><div class="panel"><h2 id="job-people-title">Người được theo dõi</h2><div id="job-people"></div></div><div class="panel job-faces"><h2 id="job-face-title">Khuôn mặt trong video</h2><div id="job-faces"></div></div><div class="panel"><h2>Thông số & hiệu năng</h2><div id="job-details"></div><div id="job-actions" class="actions"></div></div><div class="notice">Chấm dưới bounding box là điểm chân dùng để kiểm tra vùng. Độ tin cậy model không phải tỷ lệ chính xác đã kiểm chứng.</div></section></div><section class="panel"><h2>Cảnh báo của tác vụ</h2><div id="job-alerts"></div></section>`;
 let hasVideo=false;
 async function poll(){
  const [j,a,f,p]=await Promise.all([api('/jobs/'+id),api('/alerts?job_id='+id+'&limit=100'),allFaces('job_id='+encodeURIComponent(id)),api('/jobs/'+id+'/people').catch(()=>({items:[],count:0,available:false}))]);if(version!==routeVersion)return;
  $('#job-name').textContent=j.source_name;$('#job-badge').innerHTML=badge(j.status);
  if(j.status==='completed'&&!hasVideo&&j.config.source_id!==id){$('#player').innerHTML=`<video id="result-video" controls preload="metadata" src="/api/jobs/${id}/files/result.mp4"></video>`;hasVideo=true;}
  if(j.config.source_id===id&&!hasVideo){$('#player').innerHTML='<div class="empty">Phiên webcam không ghi video liên tục. Chỉ ảnh bằng chứng của cảnh báo được lưu.</div>';hasVideo=true;}
  else if(!hasVideo&&j.frames){const image=$('#live-preview');image.hidden=false;$('#preview-wait').hidden=true;image.src=`/api/jobs/${id}/files/preview.jpg?t=${Date.now()}`;}
  $('#job-progress').innerHTML=`<progress max="1" value="${j.progress}"></progress><p class="help">${Math.round(j.progress*100)}% · ${fmt(j.frames)} / ${fmt(j.total_frames)} frame · ${fmt(j.fps)} FPS xử lý</p>${j.error?`<p class="error">${esc(j.error)}</p>`:''}${j.cancel&&j.status==='running'?'<p class="help">Đã yêu cầu hủy…</p>':''}`;
  const s=j.summary, c=j.config;const data=[['Camera',c.camera_name],['Model',`${c.model} / ${c.image_size}px`],['Ngưỡng tin cậy',c.confidence],['Lưu trú',`${c.dwell_seconds}s`],['Vùng',c.zones.length],['Bỏ frame',c.stride],['Che mờ',c.redact?'Có':'Không'],['Cảnh báo',j.events],['Khuôn mặt trong video',c.recognize_faces?f.total:'Chưa bật']];
  if(s)data.push(['Thiết bị',s.device],['Người tối đa trong cùng một frame',s.peak_people],['Người ở frame cuối đã phân tích',s.last_observed_people],['Mã người đã theo dõi',s.tracked_people??'Không lưu'],['Thời gian xử lý',`${fmt(s.elapsed_seconds)}s`],['Tốc độ tổng',`${fmt(s.processing_fps)} FPS`],['Suy luận TB / p95',`${fmt(s.inference_mean_ms)} / ${fmt(s.inference_p95_ms)}ms`],['Đã phân tích',`${fmt(s.processed_duration)} / ${fmt(s.source_duration)}s`]);
  $('#job-details').innerHTML=`<dl class="detail-list">${data.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl><hr>`;
  $('#job-face-title').textContent=c.source_id===id?'Khuôn mặt từ webcam':`Khuôn mặt trong video · ${fmt(f.total)}`;
  $('#job-people-title').textContent=c.source_id===id?'Người trong phiên webcam':`Người được theo dõi · ${s?fmt(s.peak_people):fmt(j.people)} tối đa cùng lúc`;
  $('#job-people').innerHTML=c.source_id===id?'<p class="help">Webcam hiển thị số người đang thấy trực tiếp.</p>':c.redact?'<p class="help">Không lưu ảnh người vì tác vụ bật che mờ.</p>':['queued','running'].includes(j.status)?'<p class="help">Đang tổng hợp ảnh người theo dõi…</p>':personCards(id,p)+'<p class="help">Ảnh là vùng đầu/vai theo mã track, kể cả người quay lưng. Đây không phải nhận diện khuôn mặt hay xác minh danh tính; một người có thể có nhiều track nếu bị mất dấu.</p>';
  $('#job-faces').innerHTML=c.recognize_faces?(c.source_id===id?'<p class="help">Xem ảnh và tổng số khuôn mặt theo ngày tại <a href="#camera">Webcam trực tiếp</a>.</p>':faceCards(f.items)+'<p class="help">Số khuôn mặt là ước tính. Khuôn mặt quá nhỏ, mờ, quay đi hoặc bị che có thể không lưu được.</p>'):'<p class="help">Tác vụ này chưa bật lưu khuôn mặt. Hãy chạy lại video với tùy chọn “Lưu khuôn mặt”.</p>';
  $('#job-actions').innerHTML=['queued','running'].includes(j.status)?'<button id="cancel" class="danger">Hủy tác vụ</button>':`<a href="#library">Phân tích tiếp</a>${s?`<a href="/api/jobs/${id}/files/summary.json" target="_blank" rel="noopener">Báo cáo JSON</a><a href="/api/jobs/${id}/files/detections.jsonl" target="_blank" rel="noopener">Dữ liệu frame</a>`:''}`;
  if($('#cancel'))$('#cancel').onclick=async()=>{try{await api('/jobs/'+id+'/cancel',{method:'POST'});toast('Đã gửi yêu cầu hủy.');}catch(e){toast(e.message);}};
  const urgent=a.items.filter(x=>x.severity==='urgent');const urgentCount=s?.event_counts?['suspected_fall','prolonged_lying','fire','smoke'].reduce((n,k)=>n+(s.event_counts[k]||0),0):urgent.length;const hasFall=(s?.event_counts?.suspected_fall||0)>0||urgent.some(x=>x.event_type==='suspected_fall');const alarm=$('#job-alarm');alarm.hidden=!urgentCount;if(urgentCount)alarm.innerHTML=`<strong>BÁO ĐỘNG ĐỎ · ${hasFall?'NGHI TÉ NGÃ':'CẦN KIỂM TRA NGAY'}</strong><span>${urgentCount} cảnh báo khẩn. ${urgent.map(x=>`${esc(x.zone)} tại ${fmt(x.video_time)}s`).join(' · ')}</span><span>Hãy mở video và ảnh bằng chứng để xác minh.</span>`;
  $('#event-timeline').innerHTML=a.items.map(x=>`<button class="quiet ${x.severity==='urgent'?'urgent-item':''}" data-time="${x.video_time}">${fmt(x.video_time)}s · ${esc(x.zone)}</button>`).join('');document.querySelectorAll('[data-time]').forEach(b=>b.onclick=()=>{const v=$('#result-video');if(v){v.currentTime=Math.max(0,Number(b.dataset.time)-1);v.play().catch(()=>{});}});
  $('#job-alerts').innerHTML=(c.detect_interactions?'':'<p class="notice">Tác vụ này chưa bật “Nghi xung đột qua chuyển động mạnh”, nên không phân tích tương tác giữa người.</p>')+(a.items.length?`<div class="table-wrap"><table><thead><tr><th>THỜI GIAN VIDEO</th><th>VÙNG</th><th>ĐỐI TƯỢNG</th><th>TIN CẬY</th><th>TRẠNG THÁI</th><th>BẰNG CHỨNG</th></tr></thead><tbody>${a.items.map(x=>`<tr><td>${fmt(x.video_time)}s</td><td>${esc(x.zone)}</td><td>${esc(alertTrack(x))}</td><td>${fmt(x.confidence)}</td><td>${badge(x.status)}</td><td><a href="/api/alerts/${x.id}/evidence" target="_blank" rel="noopener">Xem ảnh</a></td></tr>`).join('')}</tbody></table></div><p class="help">${a.total} cảnh báo · <a href="#alerts">Duyệt và ghi chú cảnh báo</a></p>`:'<div class="empty">Chưa ghi nhận cảnh báo từ các quy tắc đã bật. Không có cảnh báo không có nghĩa video chắc chắn an toàn.</div>');
  if(['queued','running'].includes(j.status))timer=setTimeout(()=>poll().catch(e=>toast(e.message)),1000);
 }
 await poll();
}
async function alertsPage(version){
 const system=await api('/system');
 if(version!==routeVersion)return;
 $('#content').innerHTML='<div class="toolbar"><select id="alert-filter" aria-label="Lọc cảnh báo"><option value="">Tất cả trạng thái</option>'+Object.entries(labels).filter(([k])=>['new','acknowledged','resolved','false_positive'].includes(k)).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')+'</select><a href="/api/export/alerts.csv">Xuất báo cáo CSV</a><button id="refresh-alerts" class="quiet">Làm mới</button></div><p class="help" id="alerts-total"></p><div id="alert-cards" class="alert-grid"></div><div class="pagination"><button id="alerts-prev" class="quiet">Trước</button><button id="alerts-next" class="quiet">Sau</button></div>';
 let offset=0;
 const telegramLabels={delivered:'Đã gửi',telegram_not_configured:'Chưa cấu hình bot',telegram_delivery_failed:'Gửi thất bại',telegram_rejected:'Telegram từ chối',pending:'Đang chờ'};
 const retryable=new Set(['telegram_not_configured','telegram_delivery_failed','telegram_rejected']);
 async function load(){
  const d=await api('/alerts?status='+$('#alert-filter').value+'&offset='+offset);
  if(version!==routeVersion||!$('#alert-cards'))return;
  $('#alerts-total').textContent=`${d.total} cảnh báo · thời gian là mốc trong video, không phải giờ ghi hình thực tế.`;
  $('#alert-cards').innerHTML=d.items.map(a=>`<article class="panel alert-card ${a.severity==='urgent'?'urgent-card':''}"><a href="/api/alerts/${a.id}/evidence" target="_blank" rel="noopener"><img loading="lazy" src="/api/alerts/${a.id}/evidence" alt="Bằng chứng ${esc(a.zone)} tại ${fmt(a.video_time)} giây"></a><div class="alert-body">${a.severity==='urgent'?'<div class="red-alert-label">BÁO ĐỘNG ĐỎ · CẦN KIỂM TRA</div>':''}<div class="panel-head"><h3>${esc(a.zone)}</h3>${badge(a.status)}</div><p>${esc(a.camera_name)} · ${esc(a.source_name)}</p><p>Video ${fmt(a.video_time)}s · đối tượng ${esc(alertTrack(a))} · tin cậy ${fmt(a.confidence)}</p><p>${a.details?.experimental?'THỬ NGHIỆM · cần xác minh · ':''}${esc(a.severity)} · ${esc(a.details?.reason||'zone_dwell')}</p><p>Duy trì ${fmt(a.dwell)}s · ${esc(a.event_type)} · <a href="#job/${a.job_id}">Xem tác vụ</a></p><p class="telegram-delivery">Telegram: ${esc(telegramLabels[a.telegram_status]||a.telegram_status)}</p>${system.telegram_configured&&me.role!=='viewer'&&retryable.has(a.telegram_status)?`<button class="quiet" type="button" data-telegram="${a.id}">Gửi lại Telegram</button>`:''}<form data-review="${a.id}"><label>Trạng thái<select name="status">${['new','acknowledged','resolved','false_positive'].map(s=>`<option value="${s}" ${s===a.status?'selected':''}>${labels[s]}</option>`).join('')}</select></label><textarea name="note" aria-label="Ghi chú cảnh báo" maxlength="1000" placeholder="Ghi chú kiểm tra…">${esc(a.note)}</textarea><button type="submit" ${me.role==='viewer'?'disabled':''}>Lưu đánh giá</button></form></div></article>`).join('')||'<div class="empty">Chưa có cảnh báo phù hợp.</div>';
  $('#alerts-prev').disabled=offset===0;$('#alerts-next').disabled=offset+50>=d.total;
  document.querySelectorAll('[data-telegram]').forEach(button=>button.onclick=async()=>{button.disabled=true;try{const result=await api('/alerts/'+button.dataset.telegram+'/telegram',{method:'POST'});toast(result.delivered?'Đã gửi lại Telegram.':'Telegram vẫn chưa nhận được cảnh báo.');await load();}catch(error){toast(error.message);button.disabled=false;}});
  document.querySelectorAll('[data-review]').forEach(f=>f.onsubmit=async e=>{e.preventDefault();try{await api('/alerts/'+f.dataset.review,{method:'PATCH',body:JSON.stringify(Object.fromEntries(new FormData(f)))});toast('Đã lưu đánh giá.');await load();}catch(error){toast(error.message);}});
 }
 $('#alert-filter').onchange=()=>{offset=0;load().catch(e=>toast(e.message));};$('#refresh-alerts').onclick=()=>load().catch(e=>toast(e.message));$('#alerts-prev').onclick=()=>{offset=Math.max(0,offset-50);load().catch(e=>toast(e.message));};$('#alerts-next').onclick=()=>{offset+=50;load().catch(e=>toast(e.message));};await load();
}
async function systemPage(){const d=await api('/system');$('#content').innerHTML=`<section class="panel"><h2>Trạng thái hệ thống</h2><dl class="detail-list"><dt>Worker</dt><dd>${d.worker_alive?'Đang hoạt động':'Đang dừng'}</dd><dt>Dữ liệu ShanghaiTech</dt><dd>${d.dataset_available?'Đã kết nối':'Không tìm thấy'}</dd><dt>Nguồn đã lập chỉ mục</dt><dd>${d.sources}</dd><dt>YOLO11n</dt><dd>${d.models.yolo11n?'Đã tải':'Chưa tải'}</dd><dt>YOLO11s</dt><dd>${d.models.yolo11s?'Đã tải':'Chưa tải'}</dd><dt>Nhận diện khuôn mặt</dt><dd>${d.face_available?'Đã tải':'Chưa tải model'}</dd><dt>Tác vụ đồng thời</dt><dd>1 worker / hàng đợi ${d.max_queue}</dd></dl></section><div class="notice">${esc(d.detection_note)} Nhận diện khuôn mặt chỉ gom nhóm ẩn danh khi được bật; có thể đếm thiếu hoặc đếm trùng. Quy tắc tư thế không chẩn đoán ý định hay kết luận bạo lực.</div><section id="users-panel"></section>`;if(me.role==='admin'){const [users,audit]=await Promise.all([api('/users'),api('/audit')]);$('#users-panel').innerHTML=`<div class="panel"><h2>Tài khoản & phân quyền</h2><p>${users.map(u=>`${esc(u.username)} (${esc(u.role)})`).join(' · ')}</p><form id="user-form" class="form-grid"><label>Tên đăng nhập<input name="username" required maxlength="50" autocomplete="off"></label><label>Mật khẩu ≥ 12 ký tự<input name="password" type="password" required minlength="12" autocomplete="new-password"></label><label>Vai trò<select name="role"><option value="viewer">Viewer · chỉ xem</option><option value="operator">Operator · xử lý và duyệt</option><option value="admin">Admin · quản lý</option></select></label><div><button type="submit">Tạo tài khoản</button></div></form></div><div class="panel"><h2>Nhật ký thao tác gần nhất</h2><div class="table-wrap"><table><thead><tr><th>THỜI ĐIỂM</th><th>TÀI KHOẢN</th><th>THAO TÁC</th><th>ĐỐI TƯỢNG</th></tr></thead><tbody>${audit.map(a=>`<tr><td>${esc(new Date(a.at).toLocaleString('vi-VN'))}</td><td>${esc(a.username)}</td><td>${esc(a.action)}</td><td class="mono">${esc(a.target)}</td></tr>`).join('')}</tbody></table></div></div>`;$('#user-form').onsubmit=async e=>{e.preventDefault();try{await api('/users',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});toast('Đã tạo tài khoản.');await systemPage();}catch(error){toast(error.message);}};}}
async function planPage(version){
  const [plan,orders,commerce]=await Promise.all([api('/me/plan'),api(me.role==='admin'?'/admin/orders':'/me/orders'),api('/me/commerce')]);
  if(version!==routeVersion)return;
  updateAccountSummary(plan);
  const active=plan.plan==='pro_local';
  const reset=new Date(plan.video_reset_at).toLocaleDateString('vi-VN');
  const expiry=plan.expires_at?new Date(plan.expires_at).toLocaleString('vi-VN'):'Không giới hạn trong pilot nội bộ';
  const title=active?'Pro Local':plan.plan==='admin'?'Quản trị viên':'Free';
  $('#content').innerHTML=`<div class="plan-intro panel"><div><span class="eyebrow">TÀI KHOẢN LH25</span><h2>${title}</h2><p>${active?'Webcam và khuôn mặt theo ngày đã mở trên máy chạy LH25.':plan.plan==='admin'?'Quản lý yêu cầu nâng cấp và quyền sử dụng của khách.':'Phân tích video ngắn và nhận ảnh cảnh báo về Telegram riêng.'}</p></div><span class="tag">${active?'PRO LOCAL':plan.plan==='admin'?'ADMIN':'FREE'}</span></div>
    <div class="grid plan-metrics"><div class="metric"><span>Video tháng này</span><strong>${fmt(plan.video_used)}${plan.video_limit===null?'':` / ${plan.video_limit}`}</strong><small>${plan.video_limit===null?'Quản trị viên không áp hạn mức':'Làm mới '+esc(reset)}</small></div><div class="metric"><span>Webcam hôm nay</span><strong>${plan.webcam?`${fmt(plan.webcam_used_seconds_today/3600)} / ${plan.webcam_seconds_per_day===null?'∞':fmt(plan.webcam_seconds_per_day/3600)} giờ`:'Chưa mở'}</strong><small>${plan.webcam?'Làm mới 00:00 giờ Việt Nam':'Có trong Pro Local'}</small></div><div class="metric"><span>Thời hạn Pro</span><strong class="plan-expiry">${active?esc(expiry):'—'}</strong><small>${active?'Tính từ lần xác nhận thanh toán':'Chưa kích hoạt Pro'}</small></div></div>
    ${plan.plan==='free'?`<section class="panel plan-upgrade"><span class="eyebrow">NÂNG CẤP PILOT</span><h2>Thêm webcam cho ngôi nhà của bạn.</h2><p>Pro Local dự kiến ${fmt(plan.pro_price_vnd)}đ / ${plan.pro_days} ngày. Nhóm LH25 sẽ liên hệ hướng dẫn thanh toán; chưa có thu tiền trực tiếp trên web.</p><div class="actions">${plan.pending_order?`<span class="tag">Yêu cầu ${esc(plan.pending_order.id.slice(0,8))} đang chờ liên hệ</span>`:'<button id="upgrade-pro" type="button">Gửi yêu cầu Pro Local ↗</button>'}<a href="/store#pricing">Xem bảng giá</a></div><p id="plan-feedback" role="status" aria-live="polite"></p></section>`:''}
    <section class="panel"><h2>Cách bắt đầu</h2><div class="plan-steps"><span>1. <a href="#telegram">Kết nối Telegram</a> và nhận tin thử</span><span>2. <a href="#library">Phân tích video</a> của bạn</span><span>3. Mở <a href="#alerts">Cảnh báo</a> để xem bằng chứng</span></div><p class="help">Free: tối đa 3 video/tháng, mỗi video tối đa 2 phút và 100 MB. Pro Local: webcam và thư viện khuôn mặt ẩn danh theo ngày. AI có thể báo sai hoặc bỏ sót.</p></section>
    ${me.role==='admin'?`<section class="panel"><div class="panel-head"><h2>Yêu cầu Pro từ khách</h2><span class="tag">${orders.filter(o=>['requested','payment_pending'].includes(o.status)).length} CHỜ XỬ LÝ</span></div>${orders.length?`<div class="admin-orders">${orders.map(o=>`<article class="admin-order"><div><strong>${esc(o.display_name||o.username)}</strong><small>${esc(o.email||'Chưa có email')} · ${esc(o.phone||'Chưa có điện thoại')}</small><small>Mã ${esc(o.id.slice(0,8))} · ${esc(new Date(o.created_at).toLocaleString('vi-VN'))} · ${fmt(o.amount_vnd)}đ</small></div><div><span class="tag">${({requested:'CHỜ XÁC NHẬN',payment_pending:'CHỜ PAYOS',initiating:'ĐANG TẠO LINK',checkout_failed:'LỖI TẠO LINK',activated:'ĐÃ MỞ PRO',rejected:'TỪ CHỐI'})[o.status]||'CẦN KIỂM TRA'}</span>${o.status==='requested'&&!commerce.payment_enabled?`<form data-activate="${esc(o.id)}" class="order-form"><label>Mã giao dịch đã đối soát<input name="payment_reference" minlength="4" maxlength="120" required placeholder="Mã từ sao kê ngân hàng"></label><button type="submit">Xác nhận đã thu &amp; mở Pro</button><button type="button" class="quiet" data-reject="${esc(o.id)}">Từ chối</button></form>`:''}</div></article>`).join('')}</div>`:'<div class="empty">Chưa có yêu cầu Pro.</div>'}<p class="help">${commerce.payment_enabled?'PayOS tự mở Pro khi webhook hợp lệ được xác minh.':'Chỉ kích hoạt sau khi đã đối chiếu giao dịch thật. Không dùng ảnh biên lai do khách gửi làm bằng chứng duy nhất.'}</p></section>`:''}`;
  if(me.role==='admin'&&!commerce.payment_enabled){
    const waiting=orders.filter(order=>order.status==='transfer_reported').length;
    const section=$('.admin-orders')?.closest('.panel');
    if(section){
      section.querySelector('.panel-head .tag').textContent=`${orders.filter(order=>['requested','transfer_reported'].includes(order.status)).length} CHỜ ĐỐI SOÁT`;
      section.insertAdjacentHTML('beforeend',`<p class="help">${waiting} khách đã báo chuyển khoản. <a href="/admin">Mở bảng đối soát đầy đủ ↗</a> để kiểm tra sao kê và mở Pro.</p>`);
    }
  }
  if(plan.plan==='free'&&!commerce.payment_enabled){
    const upgradePanel=$('.plan-upgrade');
    upgradePanel.querySelector('p').textContent=commerce.pilot_checkout_enabled
      ?`Pro Local ${fmt(plan.pro_price_vnd)}đ / ${plan.pro_days} ngày. Bấm mua để mở ngay mã QR payOS; Pro chỉ mở sau khi Admin đối soát và duyệt.`
      :commerce.manual_transfer
      ?`Pro Local ${fmt(plan.pro_price_vnd)}đ / ${plan.pro_days} ngày. Tạo yêu cầu, chuyển khoản đúng nội dung rồi chờ Admin đối soát.`
      :`Pro Local ${fmt(plan.pro_price_vnd)}đ / ${plan.pro_days} ngày. Tạo yêu cầu; Admin sẽ gắn link payOS riêng cho đơn của bạn. Chưa thanh toán khi link chưa xuất hiện.`;
    if(commerce.pilot_checkout_enabled&&plan.pending_order?.status==='requested'&&!plan.pending_order.checkout_url&&!plan.pending_order.payment_order_code){
      const badge=upgradePanel.querySelector('.actions .tag');
      if(badge)badge.outerHTML='<button id="upgrade-pro" type="button">Tạo mã QR payOS ↗</button>';
    }
    if(plan.pending_order?.checkout_url){
      const badge=upgradePanel.querySelector('.actions .tag');
      if(badge)badge.textContent='Mã payOS đã sẵn sàng · chờ thanh toán hoặc duyệt';
    }
    if(plan.pending_order){
      const order=plan.pending_order, code=order.payment_order_code
        ?'LH25'+String(order.payment_order_code).slice(-5)
        :'LH25'+order.id.slice(0,12).toUpperCase();
      const oldPrice=order.amount_vnd!==plan.pro_price_vnd;
      const details=oldPrice
        ?`<p class="notice">Đơn này có giá cũ ${fmt(order.amount_vnd)}đ. Đừng thanh toán link cũ. Hãy nhờ Admin từ chối đơn này để tạo đơn mới giá ${fmt(plan.pro_price_vnd)}đ.</p>`
        :order.checkout_url
        ?`<h3>Thanh toán qua payOS · đơn ${esc(order.id.slice(0,8))}</h3><p>Số tiền: <strong>${fmt(order.amount_vnd)}đ</strong> · Mã đối chiếu: <strong>${esc(code)}</strong></p><p class="help">Mở link payOS để xem QR và kiểm tra số tiền, tài khoản thụ hưởng trước khi chuyển. Không nhập mật khẩu ngân hàng trên LH25.</p><a class="button" href="${esc(order.checkout_url)}" target="_blank" rel="noopener noreferrer">Mở link thanh toán payOS ↗</a><p class="help">Sau khi payOS báo đã thanh toán, hãy báo cho LH25. Admin sẽ kiểm tra giao dịch trong tài khoản payOS rồi mới mở Pro.</p>${order.status==='requested'?`<button id="report-transfer" type="button">Tôi đã thanh toán · báo để đối soát</button>`:'<p role="status">Đã báo thanh toán; đang chờ Admin đối soát payOS.</p>'}`
        :order.payment_order_code
        ?'<p class="notice">Mã payOS đã được đặt trước nhưng chưa có link thanh toán xác nhận. Admin sẽ kiểm tra và gắn link cho đơn này. Đừng tạo đơn mới hoặc chuyển khoản trước khi link xuất hiện.</p>'
        :commerce.manual_transfer
        ?`<h3>Chuyển khoản cho yêu cầu ${esc(order.id.slice(0,8))}</h3><dl class="detail-list"><dt>Ngân hàng</dt><dd>${esc(commerce.manual_transfer.bank)}</dd><dt>Người nhận</dt><dd>${esc(commerce.manual_transfer.recipient)}</dd><dt>Số tài khoản</dt><dd>${esc(commerce.manual_transfer.account)}</dd><dt>Số tiền</dt><dd>${fmt(order.amount_vnd)}đ</dd><dt>Nội dung</dt><dd><strong>${esc(code)}</strong></dd></dl><p class="help">Kiểm tra tên người nhận trong ứng dụng ngân hàng trước khi xác nhận chuyển tiền. Pro chỉ mở khi Admin đối chiếu được giao dịch thật trên sao kê; ảnh chụp chuyển khoản không tự mở quyền.</p>${order.status==='requested'?`<button id="report-transfer" type="button">Tôi đã chuyển khoản · báo để đối soát</button>`:'<p role="status">Đã báo chuyển khoản; đang chờ Admin kiểm tra sao kê.</p>'}`
        :`<p class="notice">${order.status==='initiating'?'Mã QR payOS đang được tạo. Tải lại trang sau ít phút.':'Admin chưa gắn link payOS cho đơn này. Chưa chuyển khoản hoặc thanh toán từ nơi khác. Vui lòng quay lại trang này sau.'}</p>`;
      upgradePanel.insertAdjacentHTML('beforeend',`<div class="manual-transfer">${details}</div>`);
      const report=$('#report-transfer');
      if(report)report.onclick=async()=>{if(!confirm('Bạn đã thực sự chuyển khoản đúng số tiền và nội dung chưa? Việc báo chuyển khoản không tự mở gói Pro.'))return;report.disabled=true;try{await api('/me/orders/'+encodeURIComponent(order.id)+'/report-transfer',{method:'POST'});await planPage(version);}catch(error){$('#plan-feedback').textContent=error.message;report.disabled=false;}};
    }
  }
  if(me.role!=='admin'){
    const paymentLabels={requested:'Chờ thanh toán / đối soát',transfer_reported:'Đã báo thanh toán · chờ duyệt',initiating:'Đang tạo mã payOS',payment_pending:'Chờ thanh toán',activated:'Đã mở Pro',checkout_failed:'Tạo mã payOS thất bại',rejected:'Đã từ chối'};
    $('#content').insertAdjacentHTML('beforeend',`<section class="panel"><h2>Lịch sử thanh toán</h2>${orders.length?`<div class="table-wrap"><table><thead><tr><th>Mã đơn</th><th>Số tiền</th><th>Trạng thái</th><th>Ngày tạo</th></tr></thead><tbody>${orders.map(order=>`<tr><td>${esc(order.id.slice(0,8))}</td><td>${fmt(order.amount_vnd)}đ</td><td>${esc(paymentLabels[order.status]||order.status)}</td><td>${esc(new Date(order.created_at).toLocaleString('vi-VN'))}</td></tr>`).join('')}</tbody></table></div>`:'<p class="help">Chưa có đơn hàng.</p>'}</section>`);
    if(active&&commerce.payment_enabled)$('#content').insertAdjacentHTML('beforeend','<section class="panel plan-upgrade"><h2>Gia hạn Pro</h2><p>Mua thêm 30 ngày; thời gian còn lại sẽ được cộng dồn sau thanh toán.</p><button id="upgrade-pro" type="button">Gia hạn Pro ↗</button><p id="plan-feedback" role="status"></p></section>');
  }
  if(commerce.email_required){
    const emailSection=document.createElement('section');emailSection.className='panel';
    emailSection.innerHTML=`<h2>Xác minh email</h2><p>${commerce.email_verified?'Email đã được xác minh.':'Cần xác minh email trước khi phân tích hoặc thanh toán.'}</p><p class="help">Email liên hệ: ${esc(commerce.email||'Chưa nhập')}</p>${commerce.email_verified?'':'<button id="resend-email" type="button">Gửi email xác minh ↗</button><p id="email-feedback" role="status" aria-live="polite"></p>'}`;
    $('#content').prepend(emailSection);
    const resend=$('#resend-email');if(resend)resend.onclick=async()=>{resend.disabled=true;try{await api('/email/resend',{method:'POST'});$('#email-feedback').textContent='Đã gửi liên kết. Kiểm tra hộp thư và thư rác; liên kết có hiệu lực 30 phút.';}catch(error){$('#email-feedback').textContent=error.message;resend.disabled=false;}};
  }
  const upgrade=$('#upgrade-pro');
  if(upgrade){
    if(commerce.payment_enabled){const section=upgrade.closest('.plan-upgrade');section.querySelector('p').textContent=`Pro Local ${fmt(plan.pro_price_vnd)}đ / ${plan.pro_days} ngày. Bạn sẽ được chuyển sang trang thanh toán payOS; Pro chỉ mở sau khi LH25 nhận webhook hợp lệ.`;upgrade.textContent='Thanh toán Pro Local ↗';}
    upgrade.onclick=async()=>{upgrade.disabled=true;try{if(commerce.payment_enabled){const result=await api('/orders/pro-local/checkout',{method:'POST',body:'{}'});const url=new URL(result.checkout_url);if(url.protocol!=='https:'||url.hostname!=='pay.payos.vn')throw new Error('Liên kết thanh toán không hợp lệ.');location.assign(url.href);}else{const result=await api('/orders/pro-local',{method:'POST',body:'{}'});if(result.checkout_url){const url=new URL(result.checkout_url);if(url.protocol!=='https:'||url.hostname!=='pay.payos.vn')throw new Error('Liên kết thanh toán không hợp lệ.');location.assign(url.href);}else await planPage(version);}}catch(error){$('#plan-feedback').textContent=error.message;upgrade.disabled=false;}};
  }
  document.querySelectorAll('[data-activate]').forEach(form=>form.onsubmit=async event=>{event.preventDefault();const button=form.querySelector('button[type=submit]');button.disabled=true;try{const ref=form.elements.payment_reference.value.trim();await api('/admin/orders/'+encodeURIComponent(form.dataset.activate)+'/activate',{method:'POST',body:JSON.stringify({payment_reference:ref})});toast('Đã mở Pro sau khi đối soát thanh toán.');await planPage(version);}catch(error){toast(error.message);button.disabled=false;}});
  document.querySelectorAll('[data-reject]').forEach(button=>button.onclick=async()=>{if(!confirm('Từ chối yêu cầu này?'))return;button.disabled=true;try{await api('/admin/orders/'+encodeURIComponent(button.dataset.reject)+'/reject',{method:'POST'});await planPage(version);}catch(error){toast(error.message);button.disabled=false;}});
}
async function trainingPage(version){
 const d=await api('/training');if(version!==routeVersion)return;
 const count=split=>Object.entries(d.counts).filter(([k])=>k.startsWith(split+'/')).reduce((sum,[,n])=>sum+n,0);
 const latest=d.runs.at(-1), epoch=latest?.metrics.at(-1);
 let html=`<div class="grid metrics"><div class="metric"><span>Ảnh train</span><strong>${count('train')}</strong></div><div class="metric"><span>Ảnh validation</span><strong>${count('val')}</strong></div><div class="metric"><span>Ảnh test giữ riêng</span><strong>${count('test')}</strong></div><div class="metric"><span>Epoch đã hoàn tất</span><strong>${epoch?fmt(epoch.epoch):0}</strong></div></div><div class="panel"><div class="panel-head"><h2>${esc(latest?.name||'Chưa có lần huấn luyện')}</h2><span class="tag">${latest?.finished?'ĐÃ KẾT THÚC':'CHƯA CÓ BÁO CÁO HOÀN TẤT'}</span></div><p class="help">YOLO11n · transfer learning · CPU · 3 nguồn dữ liệu. Màn hình tự cập nhật mỗi 5 giây.</p><div class="table-wrap"><table><thead><tr><th>NGUỒN</th><th>TRAIN</th><th>VALIDATION</th><th>TEST</th></tr></thead><tbody>${['shanghaitech','coco128','penn-fudan'].map(s=>`<tr><td>${s}</td><td>${d.counts['train/'+s]||0}</td><td>${d.counts['val/'+s]||0}</td><td>${d.counts['test/'+s]||0}</td></tr>`).join('')}</tbody></table></div></div><div class="notice">ShanghaiTech có nhãn người sơ bộ do model giáo viên tạo và một số ảnh đã kiểm tra trực quan. Nhãn anomaly gốc không được coi là nhãn người. Số liệu validation dùng chọn checkpoint; kết quả test dưới đây mới dùng so sánh sau train.</div>`;
 html='<div class="notice">Báo cáo huấn luyện bên dưới là thí nghiệm campus lịch sử, không phải điểm chất lượng cho té ngã, cháy/khói hoặc webcam tại nhà. Dữ liệu sự kiện mới chỉ được chuẩn bị để kiểm thử và nghiên cứu.</div>'+html;
 if(latest?.metrics.length)html+=`<div class="panel"><h2>Quá trình học — validation</h2><div class="table-wrap"><table><thead><tr><th>EPOCH</th><th>BOX LOSS</th><th>CLASS LOSS</th><th>PRECISION</th><th>RECALL</th><th>mAP50</th><th>mAP50–95</th></tr></thead><tbody>${latest.metrics.slice().reverse().map(m=>`<tr><td>${m.epoch}</td><td>${fmt(m['train/box_loss'])}</td><td>${fmt(m['train/cls_loss'])}</td><td>${fmt(100*m['metrics/precision(B)'])}%</td><td>${fmt(100*m['metrics/recall(B)'])}%</td><td>${fmt(100*m['metrics/mAP50(B)'])}%</td><td>${fmt(100*m['metrics/mAP50-95(B)'])}%</td></tr>`).join('')}</tbody></table></div></div>`;
 if(d.report){html+=`<div class="panel"><h2>So sánh trên cùng tập test · IoU 0.5 / confidence 0.35</h2><p>Model mặc định: <strong>${esc(d.report.default_model)}</strong>. ${d.report.promoted?'Model fine-tune đã đạt điều kiện thay thế.':'Model fine-tune chưa đạt toàn bộ điều kiện thay thế model mặc định.'}</p><div class="table-wrap"><table><thead><tr><th>MODEL</th><th>TP / FP / FN</th><th>PRECISION</th><th>RECALL</th><th>F1</th><th>MS / ẢNH</th></tr></thead><tbody>${d.report.results.map(r=>`<tr><td>${esc(r.model)}</td><td>${r.overall.tp} / ${r.overall.fp} / ${r.overall.fn}</td><td>${fmt(r.overall.precision*100)}%</td><td>${fmt(r.overall.recall*100)}%</td><td>${fmt(r.overall.f1*100)}%</td><td>${fmt(r.mean_latency_ms)}</td></tr>`).join('')}</tbody></table></div><p class="help">Tập campus test chỉ có 3 ảnh; COCO128 thuộc dữ liệu pretrain. Đây là phép thử phát triển quy mô nhỏ, chưa chứng minh độ chính xác toàn bộ camera trường học.</p></div>`;}
 if(d.event_dataset){const items=d.event_dataset.items||[];const sources=[...new Set(items.map(i=>i.source))];html+='<section class="panel"><h2>Dữ liệu sự kiện đã chuẩn bị</h2><p>'+items.length+' video · '+items.reduce((n,i)=>n+(i.images?.length||0),0)+' ảnh trích xuất · chỉ lưu local</p><div class="table-wrap"><table><thead><tr><th>NGUỒN</th><th>VIDEO</th><th>NHÃN</th></tr></thead><tbody>'+sources.map(s=>'<tr><td>'+esc(s)+'</td><td>'+items.filter(i=>i.source===s).length+'</td><td>'+esc([...new Set(items.filter(i=>i.source===s).map(i=>i.label))].join(', '))+'</td></tr>').join('')+'</tbody></table></div><p>Chia theo clip/nhóm, không trộn các frame gần nhau giữa train/test. Đây là dữ liệu chuẩn bị, chưa phải bằng chứng model hành vi đã được huấn luyện chính xác. Ảnh cháy cần gán bounding box trước khi train.</p><p>Lần tải còn thiếu: '+(d.event_dataset.failures?.length||0)+' mục.</p><a href="#library">Mở thư viện video nghiên cứu</a></section>';}
 if(d.phone_training){
  const p=d.phone_training,results=p.results||[];
  const state=p.status==='completed'?'ĐÃ HUẤN LUYỆN & ĐÁNH GIÁ':p.status==='failed'?'HUẤN LUYỆN BỊ GIÁN ĐOẠN':'ĐANG HUẤN LUYỆN';
  html=`<section class="panel"><div class="panel-head"><h2>Nhận diện cơ thể · dữ liệu Drive</h2><span class="tag">${state}</span></div><p>${p.train_images??114} ảnh train · ${p.val_images??9} ảnh validation · ${p.test_images??9} ảnh test · vòng ${p.epochs_completed??0}/${p.epochs??6}</p><p class="help">13 cảnh video. Ảnh chỉ còn thân người và che khuất giả lập được bổ sung vào train. Các cảnh kiểm tra được giữ riêng.</p>${results.length?`<div class="table-wrap"><table><thead><tr><th>MODEL</th><th>PRECISION</th><th>RECALL</th><th>F1</th><th>SAI SỐ ĐẾM TB</th></tr></thead><tbody>${results.map(r=>`<tr><td>${r.name==='baseline'?'Hiện tại':'Sau huấn luyện'}</td><td>${fmt(100*r.metrics.precision)}%</td><td>${fmt(100*r.metrics.recall)}%</td><td>${fmt(100*r.metrics.f1)}%</td><td>${fmt(r.count_mae)}</td></tr>`).join('')}</tbody></table></div><p>${p.candidate_passed_gate?'Model mới đạt điều kiện thử nghiệm trên tập nhỏ.':'Model mới chưa đạt điều kiện thay thế. Tiếp tục dùng model hiện tại.'}</p>`:''}<p class="help">Nhãn train/validation chủ yếu do model tạo. Test có 9 ảnh ngoài trời đã rà soát; chưa đủ để kết luận độ chính xác ở quán đông người.</p></section><details class="panel"><summary>Báo cáo cũ · tham khảo</summary>`+html+'</details>';
 }
 $('#content').innerHTML=html;if(!d.report||['training','updating'].includes(d.phone_training?.status))timer=setTimeout(()=>trainingPage(version).catch(e=>toast(e.message)),5000);
}
async function stopCamera(){
  clearTimeout(cameraTimer);
  clearTimeout(previewTimer);previewRequest?.abort();previewRequest=null;cameraViewVersion++;
  if(previewUrl){URL.revokeObjectURL(previewUrl);previewUrl=null;}
  const stream=cameraStream, session=cameraSession||sessionStorage.getItem(cameraSessionKey);
  cameraStream=null;cameraSession=null;cameraRemote=false;
  if(stream)stream.getTracks().forEach(track=>track.stop());
  if(session)try{await api('/live/'+session+'/stop',{method:'POST'});sessionStorage.removeItem(cameraSessionKey);}catch(error){if(error.status===404)sessionStorage.removeItem(cameraSessionKey);else console.warn('Could not stop camera session:',error.message);}
  if($('#camera-state'))$('#camera-state').textContent='Camera đã dừng.';
  if($('#camera-placeholder'))$('#camera-placeholder').hidden=false;
  const remotePreview=$('#camera-remote-preview');if(remotePreview){remotePreview.hidden=true;remotePreview.removeAttribute('src');}
  if($('#camera-ai-panel'))$('#camera-ai-panel').hidden=true;
  if($('#camera-preview-state'))$('#camera-preview-state').textContent='';
  if($('#camera-config'))$('#camera-config').querySelectorAll('input,select').forEach(x=>x.disabled=false);
  if($('#camera-count'))$('#camera-count').textContent='–';
  const canvas=$('#camera-overlay');if(canvas)canvas.getContext('2d').clearRect(0,0,canvas.width,canvas.height);
}
async function systemEnhancements(){
  const d=await api('/system');
  const box=document.createElement('section');box.className='panel';
  box.innerHTML=`<div class="panel-head"><h2>Telegram &amp; model an toàn</h2><span class="tag">${d.telegram_configured?'BOT READY':'SETUP NEEDED'}</span></div><dl class="detail-list"><dt>Telegram của bạn</dt><dd>${d.telegram_configured?'Sẵn sàng nhận cảnh báo':'Chưa kết nối · mở mục Telegram'}</dd><dt>Pose</dt><dd>${d.live_available?'Sẵn sàng':'Chưa tải model'}</dd><dt>Lửa / khói</dt><dd>${d.fire_available?'Sẵn sàng · thử nghiệm':'Chưa tải model'}</dd></dl><p class="help">Quản trị viên cấu hình bot token trong .env; mỗi người dùng kết nối tài khoản nhận cảnh báo ở <a href="#telegram">mục Telegram</a>. Không nhập mật khẩu Telegram vào web.</p><p class="notice">Mô hình có thể bỏ sót hoặc báo sai. Đừng dùng LH25 thay thế thiết bị báo cháy chuyên dụng hay chăm sóc khẩn cấp.</p>`;
  $('#content').prepend(box);
  if(me.role==='admin'){
    const users=await api('/users');
    const free=users.filter(item=>item.plan==='free').length, pro=users.filter(item=>item.plan==='pro_local').length;
    const panel=document.createElement('section');panel.className='panel';
    panel.innerHTML=`<div class="panel-head"><h2>Quản lý khách hàng</h2><span class="tag">${fmt(free)} FREE · ${fmt(pro)} PRO</span></div><div class="table-wrap"><table><thead><tr><th>TÀI KHOẢN</th><th>EMAIL</th><th>GÓI</th><th>HẾT HẠN</th><th>TELEGRAM</th></tr></thead><tbody>${users.map(item=>`<tr><td>${esc(item.display_name||item.username)}<small class="help"> ${esc(item.username)}</small></td><td>${esc(item.email||'Chưa nhập')}${item.email_verified?' ✓':''}</td><td>${esc(item.plan==='pro_local'?'Pro':item.plan==='admin'?'Admin':'Free')}</td><td>${item.expires_at?esc(new Date(item.expires_at).toLocaleDateString('vi-VN')):'—'}</td><td>${item.telegram_linked?'Đã kết nối':'Chưa kết nối'}</td></tr>`).join('')}</tbody></table></div><p class="help">Trong chế độ payOS, quyền Pro chỉ được cấp khi webhook thanh toán hợp lệ. Ảnh/video của từng khách được bảo vệ bằng quyền ở API.</p>`;
    $('#users-panel').prepend(panel);
  }
}
async function telegramPage(version){
  const [state,profile]=await Promise.all([api('/telegram/status'),api('/profile')]);
  if(version!==routeVersion)return;
  $('#content').innerHTML=`
    <section class="panel telegram-connect"><div class="panel-head"><h2>1. Thông tin khách hàng</h2><span class="tag">${profile.email?'ĐÃ NHẬP':'CẦN HOÀN TẤT'}</span></div>
      <form id="customer-profile" class="form-grid">
        <label>Họ tên / tên liên hệ<input name="display_name" value="${esc(profile.display_name)}" minlength="2" maxlength="100" required autocomplete="name"></label>
        <label>Email liên hệ<input name="email" type="email" value="${esc(profile.email)}" maxlength="254" required autocomplete="email"></label>
        <label>Số điện thoại (không bắt buộc)<input name="phone" type="tel" value="${esc(profile.phone)}" maxlength="25" autocomplete="tel"></label>
        <div><button type="submit">Lưu thông tin</button></div>
      </form><p class="help">Email hiện chỉ để quản lý liên hệ, chưa gửi thư xác minh hoặc thanh toán. Không nhập mật khẩu Telegram vào biểu mẫu.</p>
    </section>
    <section class="panel telegram-connect"><div class="panel-head"><h2>2. Tài khoản nhận cảnh báo</h2><span class="tag">${state.linked?'ĐÃ XÁC MINH':'CHƯA KẾT NỐI'}</span></div>
      <p>${state.linked?`Telegram ${state.telegram_username?'@'+esc(state.telegram_username):esc(state.chat_hint)} đã nhận tin xác nhận lúc ${esc(new Date(state.verified_at).toLocaleString('vi-VN'))}. Cảnh báo từ video và webcam của bạn sẽ gửi đến cuộc trò chuyện này.`:'Kết nối Telegram trước khi phân tích video hoặc mở webcam. Mỗi khách dùng chat Telegram riêng.'}</p>
      ${!state.bot_configured?'<div class="notice">Quản trị viên chưa cấu hình bot LH25. Tạo bot bằng BotFather, đặt LH25_TELEGRAM_BOT_TOKEN trong .env rồi khởi động lại LH25.</div>':''}
      <div class="actions"><button id="telegram-begin" ${state.bot_configured&&(profile.email||me.username==='admin')?'':'disabled'}>${state.linked?'Đổi tài khoản Telegram':'Tạo liên kết Telegram'}</button>${state.linked?'<button id="telegram-disconnect" class="quiet">Ngắt kết nối</button>':''}</div>
      <div id="telegram-pairing" class="telegram-pairing" hidden></div><p id="telegram-feedback" role="status" aria-live="polite"></p>
    </section>
    <section class="panel telegram-guide"><h2>3. Hướng dẫn sử dụng Telegram để nhận cảnh báo</h2><ol>
      <li><strong>Điền thông tin liên hệ</strong> ở mục 1 và nhấn Lưu.</li>
      <li><strong>Cài Telegram</strong> trên điện thoại hoặc máy tính, tạo tài khoản của bạn.</li>
      <li><strong>Nhấn “Tạo liên kết Telegram”</strong> ở mục 2. Website sẽ hiện nút mở bot LH25 và lệnh /start dùng một lần.</li>
      <li><strong>Mở bot trong Telegram</strong>, nhấn Start hoặc dán đúng lệnh /start được hiển thị. Không gửi mã cho người khác.</li>
      <li><strong>Quay lại website</strong>, nhấn “Kiểm tra &amp; xác minh”. Bot phải gửi được tin thử thì tài khoản mới được kết nối.</li>
      <li><strong>Chạy video kiểm thử:</strong> mở <a href="#library">Phân tích video</a>, tải video có người ngã, giữ model Pose và bật “Nghi té ngã”; chọn 0 giây để phân tích toàn bộ. Xem báo động đỏ trong <a href="#alerts">Cảnh báo</a> và tin nhắn Telegram của bạn. Với webcam, mở <a href="#camera">Webcam trực tiếp</a> rồi cấp quyền camera.</li>
    </ol><div class="notice">AI có thể bỏ sót hoặc báo nhầm; luôn kiểm tra bằng chứng. Telegram chỉ nhận ảnh cảnh báo, không nhận toàn bộ video hay thư viện khuôn mặt.</div></section>`;
  $('#customer-profile').onsubmit=async e=>{e.preventDefault();const button=$('button',e.target);button.disabled=true;try{await api('/profile',{method:'PUT',body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});toast('Đã lưu thông tin liên hệ.');await telegramPage(version);}catch(error){toast(error.message);button.disabled=false;}};
  $('#telegram-begin').onclick=async()=>{const button=$('#telegram-begin');button.disabled=true;try{const link=await api('/telegram/link',{method:'POST'});const box=$('#telegram-pairing');box.hidden=false;box.innerHTML=`<h3>Liên kết có hiệu lực 10 phút</h3><p><a href="${esc(link.url)}" target="_blank" rel="noopener">Mở bot LH25 trên Telegram ↗</a></p><label>Lệnh để dán vào bot nếu nút mở không hoạt động<input value="${esc(link.command)}" readonly aria-label="Lệnh ghép Telegram"></label><div class="actions"><button id="telegram-check">Kiểm tra &amp; xác minh</button></div>`;$('#telegram-feedback').textContent='Nhấn Start trong bot rồi quay lại đây để kiểm tra.';$('#telegram-check').onclick=async()=>{const check=$('#telegram-check');check.disabled=true;try{const result=await api('/telegram/check',{method:'POST'});if(result.linked&&!result.pairing_pending){toast('Telegram đã được xác minh.');await telegramPage(version);}else{$('#telegram-feedback').textContent='Chưa thấy lệnh Start hoặc bot chưa gửi được tin thử. Nếu đã gửi mà vẫn lỗi, gửi lại lệnh /start trong bot rồi nhấn kiểm tra.';}}catch(error){$('#telegram-feedback').textContent=error.message;}finally{if(check.isConnected)check.disabled=false;}};}catch(error){$('#telegram-feedback').textContent=error.message;}finally{button.disabled=false;}};
  if($('#telegram-disconnect'))$('#telegram-disconnect').onclick=async()=>{if(!confirm('Ngắt Telegram sẽ khóa phân tích mới của tài khoản này. Tiếp tục?'))return;try{await api('/telegram/link',{method:'DELETE'});await telegramPage(version);}catch(error){toast(error.message);}};
}
function drawCameraOverlay(result){
  const canvas=$(cameraRemote?'#camera-ai-overlay':'#camera-overlay'), video=cameraRemote?$('#camera-ai-image'):$('#camera-video');if(!canvas||!video)return;
  canvas.width=video.videoWidth||video.naturalWidth;canvas.height=video.videoHeight||video.naturalHeight;
  const stage=canvas.parentElement;
  const scale=Math.min(stage.clientWidth/canvas.width,stage.clientHeight/canvas.height);
  canvas.style.width=`${canvas.width*scale}px`;canvas.style.height=`${canvas.height*scale}px`;
  canvas.style.inset='auto';canvas.style.left='50%';canvas.style.top='50%';canvas.style.transform='translate(-50%,-50%)';
  const ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);
  for(const item of result.detections){
    const [x1,y1,x2,y2]=item.bbox, w=canvas.width, h=canvas.height;
    const color=(item.class_id??0)===0?'#55c7ff':'#ffbd59';
    ctx.strokeStyle=color;ctx.lineWidth=3;ctx.strokeRect(x1*w,y1*h,(x2-x1)*w,(y2-y1)*h);
    ctx.fillStyle=color;ctx.font='bold 15px Segoe UI';ctx.fillText(`${({person:"Người",car:"Ô tô",motorcycle:"Xe máy",truck:"Xe tải",bus:"Xe buýt",bicycle:"Xe đạp"})[item.label]||item.label||"Người"} #${item.track_id??"?"} · ${Math.round(item.confidence*100)}%`,x1*w+4,Math.max(18,y1*h-7));
    const pose=item.keypoints||[];const edges=[[5,6],[5,7],[7,9],[6,8],[8,10],[5,11],[6,12],[11,12],[11,13],[13,15],[12,14],[14,16]];
    ctx.strokeStyle='#f1bf75';ctx.lineWidth=2;for(const [a,b]of edges){if(pose[a]?.[2]>=.5&&pose[b]?.[2]>=.5){ctx.beginPath();ctx.moveTo(pose[a][0]*w,pose[a][1]*h);ctx.lineTo(pose[b][0]*w,pose[b][1]*h);ctx.stroke();}}
  }
  for(const item of result.hazards){const [x1,y1,x2,y2]=item.bbox;ctx.strokeStyle='#fb9b92';ctx.lineWidth=4;ctx.strokeRect(x1*canvas.width,y1*canvas.height,(x2-x1)*canvas.width,(y2-y1)*canvas.height);}
  for(const face of result.faces||[]){const [x1,y1,x2,y2]=face.bbox;ctx.strokeStyle='#55c7ff';ctx.lineWidth=2;ctx.strokeRect(x1*canvas.width,y1*canvas.height,(x2-x1)*canvas.width,(y2-y1)*canvas.height);ctx.fillStyle='#55c7ff';ctx.fillText(`${face.pending?"Mặt · đang xác nhận":`Mặt ${face.number}`}`,x1*canvas.width,Math.max(18,y1*canvas.height-6));}
}
async function cameraPage(version){
  const plan=await api('/me/plan');
  if(!plan.webcam){if(version===routeVersion)$('#content').innerHTML='<section class="panel plan-upgrade"><span class="eyebrow">PRO LOCAL</span><h2>Webcam trực tiếp dành cho Pro.</h2><p>Gói Free vẫn có thể phân tích video ngắn và nhận cảnh báo Telegram. Khi cần theo dõi webcam, gửi yêu cầu nâng cấp để nhóm LH25 liên hệ.</p><div class="actions"><a href="#plan">Xem gói của tôi ↗</a><a href="#library">Dùng video Free</a></div></section>';return;}
  const system=await api('/system');if(version!==routeVersion)return;
  $('#content').innerHTML=`<div class="camera-layout"><section class="panel"><div class="panel-head"><h2>Khung hình trực tiếp</h2><span id="camera-source-label" class="tag">WEBCAM · LOCAL</span></div><div id="camera-alarm" class="red-alarm" role="alert" hidden></div><div class="camera-stage"><video id="camera-video" autoplay muted playsinline></video><img id="camera-remote-preview" alt="Hình ảnh từ camera thiết bị khác" hidden><canvas id="camera-overlay" aria-hidden="true"></canvas><div id="camera-placeholder" class="camera-placeholder"><span class="camera-icon" aria-hidden="true">◉</span><strong>Webcam sẵn sàng kết nối</strong><span>Bật camera để xem trực tiếp và phân tích tại máy.</span></div></div><div id="camera-view-tools" class="camera-view-tools" hidden><span>Hướng hình</span><button type="button" class="quiet" data-turn="-90">↶ Trái 90°</button><button type="button" class="quiet" data-turn="90">↷ Phải 90°</button><button type="button" class="quiet" id="camera-flip">↔ Lật ngang</button><button type="button" class="quiet" id="camera-view-reset">Hướng gốc</button></div><div class="camera-legend" aria-label="Chú thích màu nhận diện"><span class="legend-person">■ Người · theo cơ thể</span><span class="legend-object">■ Vật thể</span></div><p id="camera-preview-state" class="help" aria-live="polite"></p><details id="camera-ai-panel" class="camera-ai-panel" hidden><summary>Kết quả AI · khung hình đã phân tích</summary><p class="help">Khung người và số mặt nằm trên đúng ảnh AI vừa xử lý. Hình trực tiếp phía trên cập nhật độc lập.</p><div class="camera-stage"><img id="camera-ai-image" alt="Khung hình AI đã phân tích"><canvas id="camera-ai-overlay" aria-hidden="true"></canvas></div></details><p class="camera-status"><span class="dot"></span><span id="camera-state">Camera chưa bật. Chỉ ảnh có cảnh báo mới được lưu.</span></p><p class="help">Webcam gửi ảnh từ trình duyệt; camera mạng được máy tính kết nối trực tiếp. AI xử lý trên máy tính này. Telegram chỉ nhận ảnh bằng chứng khi đã cấu hình.</p><div class="camera-actions"><button id="camera-start" ${me.role==='viewer'?'disabled':''}>Bật camera &amp; phân tích</button><button id="camera-stop" class="quiet" disabled>Dừng camera</button></div></section><div class="camera-side"><div class="metric"><span>Người đang thấy</span><strong id="camera-count">–</strong><p class="help">Đếm theo cơ thể, không cần nhìn thấy mặt. Mặt được lưu riêng khi đủ rõ.</p></div><section class="panel"><h2>Ngưỡng cảnh báo</h2><form id="camera-config"><label>Nguồn hình ảnh<select name="source_type" id="camera-source"><option value="local">Webcam của máy này</option><option value="network">Điện thoại / camera IP qua mạng</option></select></label><div id="network-camera-fields" hidden><label>Đường dẫn luồng camera<input name="camera_url" type="text" autocomplete="off" placeholder="http://192.168.1.20:8081/live.flv"></label><label>Hướng hình<select name="camera_rotation"><option value="0">Giữ hướng từ điện thoại</option><option value="90">Xoay phải 90°</option><option value="270">Xoay trái 90°</option><option value="180">Xoay 180°</option></select></label><label class="check"><input name="camera_mirror" type="checkbox">Lật ngang như camera selfie</label><p class="help">Có thể đổi ngay khi đang chạy bằng nút dưới hình. Hình AI và ảnh mặt lưu cùng hướng với hình xem. Để chữ đọc đúng chiều, chỉ bật lật ngang khi nguồn đang bị ngược.</p><label>Tài khoản camera (nếu có)<input name="camera_username" autocomplete="off" placeholder="Tài khoản đặt trong app camera"></label><label>Mật khẩu camera<input name="camera_password" type="password" autocomplete="off" placeholder="Mật khẩu đặt trong app camera"></label><p class="help">IP Camera Lite: dùng đường dẫn /live.flv. Nếu Chrome xem được nhưng web báo yêu cầu đăng nhập, điền tài khoản của app tại đây. Thông tin này chỉ dùng cho phiên kết nối, không lưu vào tác vụ.</p><p class="help">Dùng URL RTSP hoặc HTTP/MJPEG của thiết bị cùng mạng. Điện thoại cần bật tính năng/app phát luồng camera. Đây không phải địa chỉ trang quản trị camera.</p></div><label>Chất lượng nhận diện<select name="image_size"><option value="640">Cân bằng · nhanh hơn</option><option value="960">Người ở xa · chi tiết hơn, AI chậm hơn</option></select></label><label>Tên nguồn<input name="camera_name" value="Webcam trong nhà" maxlength="80" required></label><label>Số người thường có (n)<input name="expected_people" type="number" min="0" max="20" value="1" required></label><label>Giữ quá ngưỡng (giây)<input name="crowd_seconds" type="number" min="1" max="60" value="3" required></label><label>Nằm lâu (giây)<input name="lying_seconds" type="number" min="2" max="120" value="8" required></label><label class="check"><input name="detect_objects" type="checkbox" checked> Phát hiện vật thể (ô tô, xe máy, xe tải…)</label><label class="check"><input name="detect_falls" type="checkbox"> Cảnh báo nghi té ngã / nằm lâu (Pose · tốn thêm xử lý)</label><label class="check"><input name="detect_fire" type="checkbox" ${system.fire_available?'checked':'disabled'}> Cảnh báo nghi lửa / khói ${system.fire_available?'':'· chưa có model'}</label><label class="check"><input name="detect_weapons" type="checkbox" ${system.weapon_available?'':'disabled'}> Cảnh báo nghi dao / súng / vật giống hung khí ${system.weapon_available?'':'· chưa có model'}</label></form><p class="help">Đếm người ẩn danh theo khung hình; không nhận dạng danh tính. Té ngã, cháy và hung khí đều là cảnh báo thử nghiệm cần xác minh.</p><p class="help">Telegram: ${system.telegram_configured?'đã cấu hình':'chưa cấu hình · xem Hệ thống'}</p></section><section class="panel"><h2>Cảnh báo phiên này</h2><ul id="camera-alerts" class="camera-alerts"><li>Chưa có cảnh báo.</li></ul></section></div></div><div id="camera-history"></div>`;
  // Older camera markup is shared with local builds; retire its weapon control.
  $('#camera-config [name="detect_weapons"]')?.closest('label')?.remove();
  const cameraHelp=$('#camera-config')?.nextElementSibling;
  if(cameraHelp?.classList.contains('help'))cameraHelp.textContent=cameraHelp.textContent.replace('Té ngã, cháy và hung khí','Té ngã và cháy');
  const faceOption=document.createElement('label');faceOption.className='check';
  faceOption.innerHTML=`<input name="recognize_faces" type="checkbox" ${system.face_available?'checked':'disabled'}> Lưu khuôn mặt và đếm số khuôn mặt khác nhau theo ngày`;
  $('#camera-config [name="image_size"]').closest('label').insertAdjacentHTML('beforebegin',`<label>Model AI<select name="model"><option value="yolo11s">YOLO11s · ổn định</option><option value="yolo11n-pose">YOLO11n Pose · ổn định</option><option value="yolo26n" ${system.models.yolo26n?'':'disabled'}>YOLO26n · thử nghiệm</option><option value="yolo26s" ${system.models.yolo26s?'':'disabled'}>YOLO26s · thử nghiệm</option><option value="yolo26n-pose" ${system.models['yolo26n-pose']?'':'disabled'}>YOLO26n Pose · thử nghiệm</option></select></label>`);
  showModelCatalog($('#camera-config [name="model"]'),system.model_catalog,plan.plan,'yolo11s');
  $('#camera-config').append(faceOption);
  const interactionOption=document.createElement('label');interactionOption.className='check';
  interactionOption.innerHTML='<input name="detect_interactions" type="checkbox"> Thử nghiệm: nghi chuyển động mạnh giữa người (dễ báo nhầm, không xác định bạo lực)';
  $('#camera-config').append(interactionOption);
  const cameraModel=$('#camera-config [name="model"]');
  const requireCameraPose=()=>{if(!cameraModel.value.endsWith('-pose')){cameraModel.value=poseFor(cameraModel.value);toast('Cảnh báo tư thế cần model Pose; đã chuyển sang '+cameraModel.value+'.');}};
  for(const name of ['detect_falls','detect_interactions'])$('#camera-config [name="'+name+'"]').addEventListener('change',event=>{if(event.target.checked)requireCameraPose();});
  cameraModel.addEventListener('change',()=>{if(['detect_falls','detect_interactions'].some(name=>$('#camera-config [name="'+name+'"]').checked))requireCameraPose();});
  const faceHelp=document.createElement('p');faceHelp.className='help';faceHelp.textContent=system.face_available?'Ảnh đại diện và đặc trưng khuôn mặt lưu tại máy; không gửi qua Telegram.':'Chưa có model khuôn mặt. Chạy python -m scripts.download_face_models rồi khởi động lại LH25.';
  $('#camera-config').after(faceHelp);
  const facePanel=document.createElement('section');facePanel.className='panel';
  facePanel.innerHTML='<div class="panel-head"><h2>Hôm nay · <span id="camera-face-count">0</span> khuôn mặt</h2><span class="tag">ĐÃ LƯU</span></div><div id="camera-faces" class="empty">Chưa có khuôn mặt trong ngày.</div>';
  $('.camera-side').insertBefore(facePanel,$('.camera-side').lastElementChild);
  $('#camera-state').textContent='Camera chưa bật. Khi bật lưu khuôn mặt, ảnh đại diện được giữ tại máy.';
  $('#camera-source').onchange=()=>{const remote=$('#camera-source').value==='network';$('#network-camera-fields').hidden=!remote;$('[name="image_size"]').value=remote?'960':'640';$('#camera-source-label').textContent=remote?'ĐIỆN THOẠI / CAMERA IP':'WEBCAM · LOCAL';};
  let latestAI=null, changingView=false;
  const rotationInput=$('[name="camera_rotation"]'), mirrorInput=$('[name="camera_mirror"]');
  $('#camera-ai-panel').ontoggle=()=>{if(latestAI&&$('#camera-ai-panel').open)drawCameraOverlay(latestAI);};
  const resizeAI=new ResizeObserver(()=>{if(cameraRemote&&latestAI&&$('#camera-ai-panel')?.open)drawCameraOverlay(latestAI);});
  resizeAI.observe($('#camera-ai-panel'));
  async function changeView(rotation,mirror){
    if(changingView)return;
    changingView=true;cameraViewVersion++;latestAI=null;
    $('#camera-view-tools').querySelectorAll('button').forEach(b=>b.disabled=true);
    const oldRotation=rotationInput.value, oldMirror=mirrorInput.checked;
    try{
      if(cameraRemote&&cameraSession){
        $('#camera-preview-state').textContent='Đang đổi hướng hình…';
        await api('/live/'+cameraSession+'/view',{method:'PATCH',body:JSON.stringify({rotation,mirror})});
      }
      rotationInput.value=String(rotation);mirrorInput.checked=mirror;
      $('#camera-flip').setAttribute('aria-pressed',String(mirror));
      $('#camera-ai-image').removeAttribute('src');
      $('#camera-ai-overlay').getContext('2d').clearRect(0,0,$('#camera-ai-overlay').width,$('#camera-ai-overlay').height);
    }catch(error){rotationInput.value=oldRotation;mirrorInput.checked=oldMirror;toast(error.message);}
    finally{changingView=false;cameraViewVersion++;$('#camera-view-tools').querySelectorAll('button').forEach(b=>b.disabled=false);}
  }
  $('#camera-view-tools').querySelectorAll('[data-turn]').forEach(button=>button.onclick=()=>changeView((Number(rotationInput.value)+Number(button.dataset.turn)+360)%360,mirrorInput.checked));
  $('#camera-flip').onclick=()=>changeView(Number(rotationInput.value),!mirrorInput.checked);
  $('#camera-view-reset').onclick=()=>changeView(0,false);
  $('#camera-start').onclick=async()=>{
    const button=$('#camera-start');button.disabled=true;
    try{
      const remote=$('#camera-source').value==='network';
      if(!remote&&!navigator.mediaDevices?.getUserMedia)throw new Error('Trình duyệt không hỗ trợ camera tại địa chỉ này. Dùng localhost hoặc HTTPS.');
      const previous=sessionStorage.getItem(cameraSessionKey);
      if(previous){try{await api('/live/'+encodeURIComponent(previous)+'/stop',{method:'POST'});}catch(error){if(error.status!==404)throw error;}sessionStorage.removeItem(cameraSessionKey);}
      const form=new FormData($('#camera-config'));
      const video=$('#camera-video');
      cameraRemote=remote;
      video.hidden=remote;$('#camera-remote-preview').hidden=true;$('#camera-overlay').hidden=remote;$('#camera-view-tools').hidden=!remote;latestAI=null;
      if(!remote){
        cameraStream=await navigator.mediaDevices.getUserMedia({video:{width:{ideal:1280},height:{ideal:720}},audio:false});
        video.srcObject=cameraStream;await video.play();
      }else if(!String(form.get('camera_url')||'').trim()){
        throw new Error('Nhập đường dẫn luồng từ điện thoại hoặc camera IP.');
      }
      $('#camera-placeholder').hidden=!remote;
      const chosenModel=String(form.get('model'));
      const config={source_id:'live',camera_name:String(form.get('camera_name')),model:chosenModel,image_size:Number(form.get('image_size')),confidence:.3,dwell_seconds:1.5,stride:1,max_seconds:0,sequence_fps:25,redact:false,zones:[],detect_falls:form.has('detect_falls'),detect_fire:form.has('detect_fire'),detect_interactions:false,expected_people:Number(form.get('expected_people')),crowd_seconds:Number(form.get('crowd_seconds')),lying_seconds:Number(form.get('lying_seconds')),crowd_threshold:0,loiter_seconds:0};
      config.camera_rotation=remote?Number(form.get('camera_rotation')):0;
      config.camera_mirror=remote&&form.has('camera_mirror');
      config.camera_url=remote?String(form.get('camera_url')).trim():'';
      config.camera_username=remote?String(form.get('camera_username')||''):'';
      config.camera_password=remote?String(form.get('camera_password')||''):'';
      config.detect_interactions=form.has('detect_interactions');
      config.recognize_faces=form.has('recognize_faces');
      config.detect_objects=form.has('detect_objects');
      cameraSession=(await api('/live/start',{method:'POST',body:JSON.stringify(config)})).id;
      sessionStorage.setItem(cameraSessionKey,cameraSession);
      $('#camera-stop').disabled=false;$('#camera-state').textContent='Đang phân tích webcam…';$('#camera-config').querySelectorAll('input,select').forEach(x=>x.disabled=true);
      const activeSession=cameraSession;
      const active=()=>cameraSession===activeSession&&version===routeVersion;
      $('#camera-flip').setAttribute('aria-pressed',String(config.camera_mirror));
      async function previewLoop(){
        if(!active()||!cameraRemote)return;
        const viewVersion=cameraViewVersion;
        try{
          if(!changingView){
            const request=new AbortController();previewRequest=request;
            const timeout=setTimeout(()=>request.abort(),6000);
            let response,blob;
            try{
              response=await fetch('/api/live/'+activeSession+'/preview',{credentials:'same-origin',cache:'no-store',signal:request.signal});
              if(!response.ok){const error=await response.json();throw new Error(error.detail||'Mất tín hiệu camera.');}
              blob=await response.blob();
            }finally{clearTimeout(timeout);}
            if(active()&&viewVersion===cameraViewVersion){
              const next=URL.createObjectURL(blob), decoded=new Image();decoded.src=next;
              try{await decoded.decode();}catch(error){URL.revokeObjectURL(next);throw error;}
              if(!active()||viewVersion!==cameraViewVersion){URL.revokeObjectURL(next);return;}
              const preview=$('#camera-remote-preview');preview.src=next;preview.hidden=false;
              if(previewUrl)URL.revokeObjectURL(previewUrl);previewUrl=next;
              $('#camera-placeholder').hidden=true;
              $('#camera-preview-state').textContent='Hình trực tiếp · cập nhật độc lập với AI';
            }
          }
        }catch(error){if(active()&&error.name!=='AbortError'){$('#camera-preview-state').textContent='Mất hình trực tiếp: '+error.message;$('#camera-remote-preview').hidden=true;}}
        finally{if(active()&&cameraRemote)previewTimer=setTimeout(previewLoop,100);}
      }
      if(remote)previewLoop();
      const capture=document.createElement('canvas');capture.width=video.videoWidth;capture.height=video.videoHeight;
      let seenAlert=false;
      let lastFaceCount=-1,lastFaceDay='',refreshingFaces=false;
      async function frameLoop(){
        if(!active())return;
        if(changingView){cameraTimer=setTimeout(frameLoop,100);return;}
        const viewVersion=cameraViewVersion;
        try{
          let result;
          if(remote){
            result=await api('/live/'+activeSession+'/remote-frame',{method:'POST'});
            if(!active())return;
            if(viewVersion!==cameraViewVersion){cameraTimer=setTimeout(frameLoop,100);return;}
            const preview=$('#camera-ai-image');
            preview.src='data:image/jpeg;base64,'+result.preview;
            await preview.decode();
            if(!active())return;
            if(viewVersion!==cameraViewVersion){cameraTimer=setTimeout(frameLoop,100);return;}
            latestAI=result;$('#camera-ai-panel').hidden=false;
          }else{
            capture.getContext('2d').drawImage(video,0,0,capture.width,capture.height);
            const blob=await new Promise(resolve=>capture.toBlob(resolve,'image/jpeg',.9));
            if(!blob)throw new Error('Không chụp được frame từ camera.');
            const data=new FormData();data.append('file',blob,'frame.jpg');
            result=await api('/live/'+activeSession+'/frame',{method:'POST',body:data});
          }
          if(!active())return;
          $('#camera-count').textContent=result.people;drawCameraOverlay(result);
          if(config.recognize_faces&&result.face_day){
            $('#camera-face-count').textContent=result.face_count_today;
            if(!refreshingFaces&&(result.face_count_today!==lastFaceCount||result.face_day!==lastFaceDay)){
              lastFaceCount=result.face_count_today;lastFaceDay=result.face_day;
              refreshingFaces=true;
              (async()=>{
                const selected=$('#camera-history [data-face-day].active')?.dataset.faceDay;
                if(!selected||selected===result.face_day)await cameraFaceHistory(result.face_day,version);
                else {const found=await allFaces('day='+encodeURIComponent(result.face_day));if((cameraStream||cameraRemote)&&version===routeVersion)$('#camera-faces').innerHTML=faceCards(found.items,true);}
              })().catch(error=>{lastFaceCount=-1;console.warn('Face gallery:',error.message);}).finally(()=>{refreshingFaces=false;});
            }
          }
          if(result.alerts.length){
            const list=$('#camera-alerts');if(!seenAlert){list.innerHTML='';seenAlert=true;}
            for(const alert of result.alerts){const li=document.createElement('li');li.className=alert.severity==='urgent'?'urgent-item':'';li.textContent=`${alert.zone} · ${Math.round(result.time)}s · Telegram: ${alert.telegram_status}`;list.prepend(li);if(alert.severity==='urgent'){const alarm=$('#camera-alarm');alarm.hidden=false;alarm.textContent=`BÁO ĐỘNG ĐỎ · ${alert.zone} · cần kiểm tra ngay`;}}
          }
          $('#camera-state').textContent=`Đang phân tích · ${result.people} người · ${result.objects||0} vật thể · ${Math.round(result.time)}s · AI ${result.processing_ms??"–"} ms`;
        }catch(error){if(error.status===409||error.status===403){await stopCamera();if($('#camera-state'))$('#camera-state').textContent='Đã dừng camera: '+error.message;return;}if(active())$('#camera-state').textContent='Lỗi phân tích: '+error.message;}
        if(active())cameraTimer=setTimeout(frameLoop,100);
      }
      frameLoop();
    }catch(error){await stopCamera();button.disabled=false;$('#camera-state').textContent=error.message;}
  };
  $('#camera-stop').onclick=async()=>{await stopCamera();$('#camera-start').disabled=false;$('#camera-stop').disabled=true;$('#camera-config').querySelectorAll('input,select').forEach(x=>x.disabled=false);};
  window.addEventListener('hashchange',()=>resizeAI.disconnect(),{once:true});
  await cameraFaceHistory(null,version);
}
const bootAuthRevision=authRevision;
api('/me').then(u=>{if(bootAuthRevision!==authRevision)return;me=u;enter();}).catch(()=>{if(bootAuthRevision===authRevision)showLogin();});


function confirmFaceDelete(title, message){
  return new Promise(resolve=>{
    const dialog=document.createElement('dialog');dialog.className='face-dialog';
    dialog.innerHTML=`<form method="dialog"><span class="face-dialog-icon">↺</span><h2>${esc(title)}</h2><p>${esc(message)}</p><div class="actions"><button class="quiet" value="cancel">Giữ lại</button><button class="danger" value="delete">Xóa dữ liệu</button></div></form>`;
    dialog.addEventListener('close',()=>{const ok=dialog.returnValue==='delete';dialog.remove();resolve(ok);},{once:true});
    document.body.append(dialog);dialog.showModal();
  });
}
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-delete-face],[data-delete-day]');if(!button||button.disabled)return;
  const day=button.dataset.deleteDay;
  const selected=day||$('#camera-history [data-face-day].active')?.dataset.faceDay;
  const version=routeVersion;
  if(!await confirmFaceDelete(day?'Bắt đầu lại ngày này?':'Xóa khuôn mặt này?',
    'Ảnh đại diện và dữ liệu nhận diện đã chọn sẽ được xóa vĩnh viễn. Camera sẽ dừng để tránh lưu lại ngay. Bạn có thể bật lại camera để kiểm tra lượt mới.'))return;
  button.disabled=true;
  try{
    if(cameraStream||cameraRemote||cameraSession)await stopCamera();
    const result=await api(day?'/faces?day='+encodeURIComponent(day):'/faces/'+encodeURIComponent(button.dataset.deleteFace),{method:'DELETE'});
    if(version!==routeVersion)return;
    if($('#camera-start'))$('#camera-start').disabled=me.role==='viewer';
    if($('#camera-stop'))$('#camera-stop').disabled=true;
    $('#camera-config')?.querySelectorAll('input,select').forEach(input=>input.disabled=false);
    await cameraFaceHistory(selected,version);
    toast(`Đã xóa ${result.deleted} khuôn mặt. Bật lại camera để thử lượt mới.`);
  }catch(error){toast(error.message);button.disabled=false;}
});
