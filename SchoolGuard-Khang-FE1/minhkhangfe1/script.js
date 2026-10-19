'use strict';

const $ = id => document.getElementById(id);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const STATUS_LABELS = {new:'Mới', processing:'Đang xử lý', resolved:'Đã xử lý', other:'Khác'};
const modules = new Map();
let mode = 'backend', baseUrl = 'http://127.0.0.1:8000', token = null, username = '';
let sessionVersion = 0, pageVersion = 0, refreshVersion = 0, currentPage = 'dashboard';
let pageController = new AbortController(), refreshController = null, moduleCleanup = null;
let loginBusy = false, refreshBusy = false, toastTimer = null, evidenceVersion = 0, evidenceUrl = null;
let evidenceController = null, snapshot = null;
let selectedChartDay = null, lastSuccessAt = null;

function readPreference(key, fallback) { try { return localStorage.getItem(key) || fallback; } catch { return fallback; } }
function writePreference(key, value) { try { localStorage.setItem(key, value); } catch {} }
function abortError() { return new DOMException('Đã hủy yêu cầu', 'AbortError'); }
function isAbort(error) { return error?.name === 'AbortError'; }
function toast(message) {
  $('toast').textContent = message; $('toast').hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('toast').hidden = true; }, 4500);
}
function validateBaseUrl(value) {
  const u = new URL(value);
  if (!['http:', 'https:'].includes(u.protocol) || u.username || u.password || u.search || u.hash || !['', '/'].includes(u.pathname)) {
    throw Error('Máy chủ phải là địa chỉ HTTP(S), không kèm đường dẫn hoặc tài khoản.');
  }
  return u.origin;
}
function normalizeStatus(value) {
  const s = String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/đ/g, 'd').trim();
  return ({'moi':'new','new':'new','dang xu ly':'processing','processing':'processing','da xu ly':'resolved','resolved':'resolved'})[s] || 'other';
}
function dateValue(value) { const d = new Date(value); return Number.isFinite(d.getTime()) ? d : null; }
function localDay(value) {
  const d = dateValue(value); if (!d) return '';
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}
function timeLabel(value) { return dateValue(value)?.toLocaleString('vi-VN') || 'Không rõ thời gian'; }
function cameraLabel(status) {
  return ({online:'Trực tuyến', active:'Trực tuyến', running:'Đang chạy', offline:'Ngoại tuyến', idle:'Chưa chạy', error:'Lỗi'})[status] || 'Chưa xác định';
}
function isOnline(camera) { return ['online','active','running'].includes(camera.status); }
function errorMessage(error) { return error?.message || 'Không tải được dữ liệu.'; }
function validationMessage(detail) {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map(item => `${(item.loc || []).filter(x => x !== 'body').join('.')}: ${item.msg || 'Không hợp lệ'}`).join('; ');
  return '';
}

// BE2: POST /token uses form-urlencoded, all protected routes use Bearer.
async function request(path, options = {}) {
  if (typeof path !== 'string' || !path.startsWith('/') || path.startsWith('//') || path.includes('\\')) throw Error('Đường dẫn API không hợp lệ.');
  const target = new URL(path, baseUrl);
  if (target.origin !== baseUrl) throw Error('Không gửi yêu cầu sang máy chủ khác.');
  if (options.signal?.aborted) throw abortError();
  if (mode === 'demo') return demoRequest(path, options);
  const usedToken = token, version = sessionVersion;
  const controller = new AbortController();
  const cancel = () => controller.abort();
  options.signal?.addEventListener('abort', cancel, {once:true});
  const timer = setTimeout(() => controller.abort(), options.timeout || 15000);
  try {
    const headers = new Headers(options.headers || {});
    if (usedToken && !options.public) headers.set('Authorization', `Bearer ${usedToken}`);
    const response = await fetch(target.href, {method:options.method || 'GET', body:options.body, headers, signal:controller.signal, credentials:'omit', cache:'no-store', redirect:'error'});
    if (!response.ok) {
      let payload; try { payload = await response.json(); } catch {}
      if (response.status === 401 && !options.public && usedToken && token === usedToken && version === sessionVersion) {
        endSession(); $('loginError').textContent = 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.';
      }
      const error = Error(validationMessage(payload?.detail) || `Không thực hiện được yêu cầu (HTTP ${response.status}).`);
      error.status = response.status; throw error;
    }
    if (options.image) {
      const blob = await response.blob();
      if (!['image/jpeg','image/png','image/webp'].includes(blob.type.split(';')[0])) throw Error('Máy chủ không trả về ảnh hợp lệ.');
      return blob;
    }
    if (response.status === 204) return null;
    try { return await response.json(); } catch { throw Error('Dữ liệu máy chủ trả về không phải JSON hợp lệ.'); }
  } catch (error) {
    if (options.signal?.aborted) throw abortError();
    if (controller.signal.aborted) throw Error('Máy chủ phản hồi quá chậm. Vui lòng thử lại.');
    if (error?.name === 'TypeError') throw Error('Không kết nối được máy chủ. Kiểm tra địa chỉ, backend và quyền CORS.');
    throw error;
  } finally { clearTimeout(timer); options.signal?.removeEventListener('abort', cancel); }
}
const API = {
  request,
  get(path, options = {}) { return request(path, options); },
  send(path, method, data, options = {}) { return request(path, {...options, method, body:JSON.stringify(data), headers:{...options.headers, 'Content-Type':'application/json'}}); }
};

function validRow(kind, row) {
  if (!row || typeof row !== 'object' || !['string','number'].includes(typeof row.id)) return false;
  if (kind === 'alerts') return typeof row.status === 'string' && typeof row.timestamp === 'string' && typeof row.camera_id === 'string';
  if (kind === 'events') return typeof row.occurred_at === 'string' && typeof row.zone_name === 'string';
  if (kind === 'cameras') return typeof row.name === 'string' && typeof row.status === 'string';
  if (kind === 'zones') return typeof row.name === 'string';
  return false;
}
async function loadList(kind, signal) {
  const paged = ['alerts','events'].includes(kind), rows = [], seen = new Set();
  for (let skip = 0; skip <= 500000; skip += 500) {
    const data = await API.get(`/api/${kind}${paged ? `?skip=${skip}&limit=500` : ''}`, {signal});
    if (signal?.aborted) throw abortError();
    if (!Array.isArray(data) || data.some(row => !validRow(kind, row))) throw Error(`Dữ liệu ${kind} không đúng cấu trúc BE2.`);
    let added = 0;
    for (const row of data) { const key = String(row.id); if (!seen.has(key)) { seen.add(key); rows.push(row); added++; } }
    if (!paged || data.length < 500) return rows;
    if (!added) throw Error('Máy chủ trả lại cùng một trang dữ liệu.');
  }
  throw Error('Dữ liệu quá lớn để tổng hợp trên trình duyệt. Cần API thống kê từ máy chủ.');
}
function summarize(alerts, cameras, now = new Date()) {
  const counts = {new:0, processing:0, resolved:0, other:0};
  for (const a of alerts) counts[normalizeStatus(a.status)]++;
  return {total:alerts.length, counts, today:alerts.filter(a => localDay(a.timestamp) === localDay(now)).length,
    active:cameras.filter(isOnline).length,
    recent:[...alerts].sort((a,b) => (dateValue(b.timestamp)?.getTime() || 0) - (dateValue(a.timestamp)?.getTime() || 0)).slice(0,5),
    days:Array.from({length:7}, (_,i) => {const d = new Date(now); d.setDate(d.getDate()-6+i); return {date:localDay(d),label:`${d.getDate()}/${d.getMonth()+1}`,count:alerts.filter(a => localDay(a.timestamp) === localDay(d)).length};})};
}

async function authenticate(name, password, signal) {
  const data = await request('/token', {method:'POST', public:true, signal, headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({username:name,password}).toString()});
  if (!data || typeof data.access_token !== 'string' || !data.access_token || String(data.token_type).toLowerCase() !== 'bearer') throw Error('API đăng nhập không trả Bearer token hợp lệ.');
  return data.access_token;
}
function setMenu(open) {
  $('sidebar').classList.toggle('mobile-open', open); $('menuBackdrop').hidden = !open;
  $('menuButton').setAttribute('aria-expanded', String(open));
  $('sidebar').inert = !open && !!window.matchMedia?.('(max-width: 760px)').matches;
}
function disposePage() {
  pageController.abort(); pageController = new AbortController();
  refreshController?.abort(); refreshVersion++; refreshBusy = false;
  if (moduleCleanup) { try { moduleCleanup(); } catch {} moduleCleanup = null; }
}
function endSession() {
  token = null; username = ''; sessionVersion++; pageVersion++; snapshot = null;
  disposePage(); closeEvidence(); setMenu(false);
  $('app').hidden = true; $('login').hidden = false; $('password').value = '';
  $('lastSync').textContent = 'Chưa cập nhật'; lastSuccessAt = null; selectedChartDay = null; $('content').classList.remove('data-stale'); setConnection('idle'); $('username').focus();
  window.dispatchEvent(new CustomEvent('schoolguard:logout'));
}
function refreshNav() {
  $('moduleNavigation').innerHTML = [...modules].map(([name,m]) => `<button type="button" data-page="${name}"><span aria-hidden="true">${name === 'camera' ? '▣' : '◉'}</span> ${escapeHTML(m.label)}</button>`).join('');
}
async function navigate(name) {
  if (!token || !['dashboard','settings',...modules.keys()].includes(name)) return;
  closeEvidence(); disposePage(); setMenu(false); currentPage = name; const version = ++pageVersion;
  document.querySelectorAll('[data-page]').forEach(b => { const active = b.dataset.page === name; b.classList.toggle('active',active); b.setAttribute('aria-current', active ? 'page' : 'false'); });
  $('pageTitle').textContent = name === 'dashboard' ? 'Tổng quan an ninh' : name === 'settings' ? 'Giao diện' : modules.get(name).label;
  $('pageSubtitle').textContent = name === 'dashboard' ? 'Theo dõi sự kiện và tình trạng khuôn viên.' : '';
  $('content').innerHTML = name === 'dashboard' ? dashboardSkeleton() : '<div class="panel loading" role="status"><span class="spinner"></span>Đang tải dữ liệu…</div>';
  if (name === 'dashboard') await refreshDashboard();
  else if (name === 'settings') renderSettings();
  else {
    $('content').innerHTML = '<div id="moduleMount"></div>';
    try {
      const mount = $('moduleMount');
      const cleanup = await modules.get(name).render(mount, {API,signal:pageController.signal,mode,username,escapeHTML,toast,navigate});
      if (version !== pageVersion) { if (typeof cleanup === 'function') cleanup(); return; }
      if (typeof cleanup === 'function') moduleCleanup = cleanup;
    } catch (error) { if (version === pageVersion && !isAbort(error)) $('content').innerHTML = `<div class="panel error" role="alert">${escapeHTML(errorMessage(error))}</div>`; }
  }
}
function failurePanel(error, label) { return `<div class="inline-error" role="alert"><strong>${escapeHTML(label)}</strong><p>${escapeHTML(errorMessage(error))}</p></div>`; }
function emptyState(text) { return `<div class="empty-state"><span aria-hidden="true">◇</span><p>${escapeHTML(text)}</p></div>`; }
function alertRows(alerts, cameras) {
  if (!alerts.length) return emptyState('Chưa có cảnh báo được ghi nhận.');
  const names = new Map(cameras.map(c => [String(c.id), c.name]));
  return `<div class="tablewrap"><table><thead><tr><th>Sự kiện</th><th>Vị trí</th><th>Thời gian</th><th>Trạng thái</th><th>Ảnh</th></tr></thead><tbody>${alerts.map(a => {
    const s = normalizeStatus(a.status);
    return `<tr class="${s==='new'?'alert-unread':''}"><td><b>#${escapeHTML(a.id)}</b><small>${escapeHTML(names.get(a.camera_id) || a.camera_id)}</small></td><td>${escapeHTML(a.location || a.zone_name || 'Chưa xác định')}</td><td>${escapeHTML(timeLabel(a.timestamp))}</td><td><span class="pill ${s==='new'?'red':s==='processing'?'blue':''}">${escapeHTML(STATUS_LABELS[s] === 'Khác' ? a.status : STATUS_LABELS[s])}</span></td><td><button type="button" class="secondary" data-evidence-kind="alerts" data-evidence-id="${escapeHTML(a.id)}" aria-label="Xem ảnh cảnh báo ${escapeHTML(a.id)}">Xem ảnh</button></td></tr>`;
  }).join('')}</tbody></table></div>`;
}
function renderDashboard(data) {
  const alerts = data.alerts.items || [], cameras = data.cameras.items || [], zones = data.zones.items || [];
  const s = summarize(alerts, cameras), ok = !data.alerts.error;
  const metrics = [['Tổng cảnh báo',ok?s.total:'—','Sự kiện được ghi nhận'],['Chưa xử lý',ok?s.counts.new+s.counts.processing:'—','Mới và đang xử lý'],['Đã xử lý',ok?s.counts.resolved:'—','Hoàn thành xác minh'],['Camera trực tuyến',data.cameras.error?'—':s.active,'Theo trạng thái camera']];
  const progress = ok && s.total ? Object.entries(s.counts).filter(([,n])=>n).map(([key,n]) => `<div class="barrow"><span>${STATUS_LABELS[key]}</span><div class="bar"><i style="width:${n/s.total*100}%"></i></div><b>${n}</b></div>`).join('') : emptyState('Chưa có dữ liệu xử lý.');
  // Activity bars use actual daily counts, without invented trend percentages.
  const zoneMap = new Map(zones.map(z=>[z.id,z.name]));
  $('content').innerHTML = `<div class="row between dashboard-toolbar"><div class="row"><span class="pill ${mode==='demo'?'blue':''}">${mode==='demo'?'DỮ LIỆU MẪU':'DỮ LIỆU HỆ THỐNG'}</span><small>${ok?s.today+' cảnh báo hôm nay':'Chưa lấy được dữ liệu cảnh báo'}</small></div><button type="button" class="secondary" id="refresh"><span aria-hidden="true">↻</span> Làm mới</button></div>
    <div class="cards">${metrics.map(([label,n,sub],i)=>`<div class="card metric-card metric-tone-${i}"><div class="metric-heading"><small>${label}</small><span class="metric-icon" aria-hidden="true">${metricIcon(i)}</span></div><div class="metric">${n}</div><small class="metric-caption">${sub}</small></div>`).join('')}</div>
    <div class="grid"><section class="panel"><div class="row between"><h2>Cảnh báo gần đây</h2><small>5 sự kiện mới nhất</small></div>${data.alerts.error?failurePanel(data.alerts.error,'Không tải được cảnh báo'):alertRows(s.recent,cameras)}</section><section class="panel"><h2>Tiến độ xử lý</h2>${data.alerts.error?failurePanel(data.alerts.error,'Chưa có thống kê'):progress}</section></div>
    <div class="grid"><section class="panel"><div class="row between"><h2>Hoạt động 7 ngày</h2><small>Theo giờ trên thiết bị</small></div>${data.alerts.error?failurePanel(data.alerts.error,'Không tải được biểu đồ'):renderActivityChart(s.days)}</section>
    <section class="panel"><div class="row between"><h2>Camera trong khuôn viên</h2><small>${data.cameras.error?'':cameras.length+' thiết bị'}</small></div>${data.cameras.error?failurePanel(data.cameras.error,'Không tải được camera'):cameras.length?cameras.map(c=>`<div class="camera-item"><div class="row"><span class="camera-symbol" aria-hidden="true">▣</span><div><b>${escapeHTML(c.name)}</b><small>${escapeHTML(data.zones.error?'Không tải được vị trí':zoneMap.get(c.zone_id)||'Chưa gán khu vực')}</small></div></div><span class="pill ${isOnline(c)?'':'neutral'}">${escapeHTML(cameraLabel(c.status))}</span></div>`).join(''):emptyState('Chưa có camera được khai báo.')}${data.zones.error?failurePanel(data.zones.error,'Không tải được khu vực'):''}</section></div>
    <section class="panel"><div class="row between"><h2>Sự kiện nhận diện gần đây</h2><small>Nguồn phân tích AI</small></div>${renderEvents(data.events)}</section>`;
}
function metricIcon(index) {
  const paths = ['<rect x="4" y="3" width="16" height="18" rx="3"/><path d="M8 8h8M8 12h8M8 16h5"/>','<path d="M12 3 2 20h20L12 3Z"/><path d="M12 9v5m0 3v.5"/>','<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>','<rect x="3" y="6" width="13" height="12" rx="3"/><path d="m16 10 5-3v10l-5-3"/>'];
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${paths[index]}</svg>`;
}
function dashboardSkeleton() {
  return `<div class="dashboard-skeleton" role="status" aria-label="Đang tải tổng quan"><span class="sr-only">Đang tải tổng quan an ninh…</span><div class="skeleton-toolbar" aria-hidden="true"><i class="skeleton-line"></i><i class="skeleton-button"></i></div><div class="cards" aria-hidden="true">${Array.from({length:4},()=>'<div class="card skeleton-card"><i class="skeleton-line short"></i><i class="skeleton-value"></i><i class="skeleton-line"></i></div>').join('')}</div><div class="grid" aria-hidden="true"><div class="panel skeleton-panel"><i class="skeleton-line short"></i>${Array.from({length:4},()=>'<i class="skeleton-row"></i>').join('')}</div><div class="panel skeleton-panel"><i class="skeleton-line short"></i>${Array.from({length:3},()=>'<i class="skeleton-row"></i>').join('')}</div></div></div>`;
}
function renderActivityChart(days) {
  const max = Math.max(1,...days.map(d=>d.count));
  if(!days.some(d=>d.date===selectedChartDay))selectedChartDay=days.at(-1).date;
  const selected=days.find(d=>d.date===selectedChartDay);
  return `<div class="activity-header"><span class="activity-total"><b>${days.reduce((n,d)=>n+d.count,0)}</b> cảnh báo trong 7 ngày</span><span class="chart-legend"><i></i>Cảnh báo</span></div><div class="activity-chart" role="group" aria-label="Số cảnh báo theo ngày">${days.map((d,i)=>`<button type="button" class="chart-point ${i===days.length-1?'is-today':''}" data-chart-day="${d.date}" data-chart-label="${d.label}" data-chart-count="${d.count}" aria-pressed="${d.date===selectedChartDay}" aria-label="${d.label}${i===days.length-1?', hôm nay':''}: ${d.count} cảnh báo"><span class="chart-tooltip" aria-hidden="true">${d.label} · ${d.count} cảnh báo</span><span class="chart-bar-track" aria-hidden="true"><i class="chart-column-fill" style="height:${Math.max(3,d.count/max*100)}%"></i></span><span class="chart-day-label">${d.label}</span>${i===days.length-1?'<span class="today-dot" aria-hidden="true"></span>':''}</button>`).join('')}</div><div id="chartSelection" class="chart-selection" aria-live="polite">${selected.label} · ${selected.count} cảnh báo${selected.date===localDay(new Date())?' · Hôm nay':''}</div>`;
}
function selectChartDay(button) {
  selectedChartDay=button.dataset.chartDay;
  document.querySelectorAll('[data-chart-day]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.chartDay===selectedChartDay)));
  if($('chartSelection'))$('chartSelection').textContent=`${button.dataset.chartLabel} · ${button.dataset.chartCount} cảnh báo${selectedChartDay===localDay(new Date())?' · Hôm nay':''}`;
}
function setConnection(state, message='') {
  const titles={idle:'Sẵn sàng kết nối',loading:'Đang cập nhật dữ liệu',connected:'Kết nối ổn định',partial:'Dữ liệu chưa đầy đủ',error:'Không tải được dữ liệu',offline:'Thiết bị đang ngoại tuyến',recheck:'Chờ kiểm tra kết nối',demo:'Không gian xem trước'};
  $('connectionStatus').dataset.state=state;
  $('connectionTitle').textContent=titles[state]||titles.idle;
  $('connectionMessage').textContent=message;
  $('connectionRetry').hidden=!['partial','error','offline','recheck'].includes(state);
  $('connectionRetry').disabled=refreshBusy;
}

function renderEvents(result) {
  if (result.error) return failurePanel(result.error,'Không tải được sự kiện nhận diện');
  const events = [...result.items].sort((a,b)=>(dateValue(b.occurred_at)?.getTime()||0)-(dateValue(a.occurred_at)?.getTime()||0)).slice(0,5);
  if (!events.length) return emptyState('Chưa có sự kiện nhận diện.');
  return `<div class="tablewrap"><table><thead><tr><th>Đối tượng</th><th>Khu vực</th><th>Nguồn</th><th>Thời gian</th><th>Ảnh</th></tr></thead><tbody>${events.map(e=>`<tr><td><b>${escapeHTML(e.object_type || 'Đối tượng')}</b><small>#${escapeHTML(e.id)}</small></td><td>${escapeHTML(e.zone_name)}</td><td>${escapeHTML(e.source_id || e.source_type || '—')}</td><td>${escapeHTML(timeLabel(e.occurred_at))}</td><td><button class="secondary" type="button" data-evidence-kind="events" data-evidence-id="${escapeHTML(e.id)}">Xem ảnh</button></td></tr>`).join('')}</tbody></table></div>`;
}
async function refreshDashboard() {
  if (!token || currentPage !== 'dashboard') return;
  refreshController?.abort(); refreshController = new AbortController();
  const signal = refreshController.signal, version = ++refreshVersion, page = pageVersion, session = sessionVersion;
  refreshBusy = true;
  setConnection(mode==='demo'?'demo':'loading',mode==='demo'?'Dữ liệu minh họa trên trình duyệt.':'Đang lấy cảnh báo và trạng thái khuôn viên.');
  const button = $('refresh'); if (button) { button.disabled = true; button.textContent = 'Đang cập nhật…'; }
  $('content').setAttribute('aria-busy','true');
  try {
    const kinds = ['alerts','cameras','zones','events'];
    const results = await Promise.allSettled(kinds.map(kind=>loadList(kind,signal)));
    if (signal.aborted || !token || session !== sessionVersion || page !== pageVersion || version !== refreshVersion) return;
    const data = Object.fromEntries(kinds.map((kind,i)=>[kind,results[i].status==='fulfilled'?{items:results[i].value}:{error:results[i].reason}]));
    const allOk = results.every(r=>r.status==='fulfilled');
    const allFailed = results.every(r=>r.status==='rejected');
    if(allFailed && snapshot && button && Object.values(snapshot).some(r=>Array.isArray(r.items))) {
      $('content').classList.add('data-stale');
      setConnection('error','Đang hiển thị dữ liệu lần cập nhật trước. Bấm Thử lại để kết nối.');
      return;
    }
    snapshot = data; renderDashboard(data); $('content').classList.remove('data-stale');
    if(allOk)lastSuccessAt=new Date();
    setConnection(mode==='demo'?'demo':allOk?'connected':allFailed?'error':'partial',mode==='demo'?'Dữ liệu minh họa trên trình duyệt.':allOk?`Cập nhật lúc ${lastSuccessAt.toLocaleTimeString('vi-VN')}`:allFailed?'Chưa nhận được dữ liệu từ máy chủ.':'Một số nguồn chưa phản hồi. Bấm Thử lại để cập nhật.');
    $('lastSync').textContent = `${allOk?'Cập nhật':'Cập nhật một phần'} ${new Date().toLocaleTimeString('vi-VN')}`;
  } finally { if (version === refreshVersion) { refreshBusy = false; $('content').setAttribute('aria-busy','false'); const refresh=$('refresh'); if(refresh){refresh.disabled=false;refresh.innerHTML='<span aria-hidden="true">↻</span> Làm mới';} $('connectionRetry').disabled=false; } }
}
function renderSettings() {
  $('content').innerHTML = `<div class="panel preference-panel"><div class="section-kicker">CÁ NHÂN HÓA</div><h2>Giao diện làm việc</h2><div class="theme-choices"><button type="button" data-set-theme="light" class="theme-choice"><span aria-hidden="true">☀</span>Sáng</button><button type="button" data-set-theme="dark" class="theme-choice"><span aria-hidden="true">☾</span>Tối</button></div></div>`;
  applyTheme(document.documentElement.dataset.theme);
}
function closeEvidence() {
  evidenceVersion++; evidenceController?.abort(); evidenceController = null;
  if ($('evidenceDialog').open) $('evidenceDialog').close();
  if (evidenceUrl) { URL.revokeObjectURL(evidenceUrl); evidenceUrl = null; }
  $('evidenceContent').innerHTML = '';
}
async function showEvidence(kind, id) {
  if (!token || !['alerts','events'].includes(kind) || !/^\d+$/.test(String(id))) return;
  const known = snapshot?.[kind]?.items?.some(row=>String(row.id)===String(id)); if (!known) return;
  closeEvidence(); const version = evidenceVersion, session = sessionVersion;
  evidenceController = new AbortController();
  $('evidenceTitle').textContent = `${kind==='alerts'?'Cảnh báo':'Sự kiện nhận diện'} #${id}`;
  $('evidenceContent').innerHTML = '<div class="loading" role="status">Đang tải ảnh…</div>';
  $('evidenceDialog').showModal();
  try {
    const blob = await API.get(`/api/${kind}/${encodeURIComponent(id)}/image`, {image:true,signal:evidenceController.signal});
    if (!token || session!==sessionVersion || version!==evidenceVersion || !$('evidenceDialog').open) return;
    evidenceUrl = URL.createObjectURL(blob);
    $('evidenceContent').innerHTML = '<img id="evidenceImage" class="evidence-image" alt="Ảnh sự kiện đã được ghi nhận">';
    $('evidenceImage').src = evidenceUrl;
  } catch (error) { if (version===evidenceVersion && !isAbort(error)) $('evidenceContent').innerHTML = failurePanel(error,'Không mở được ảnh sự kiện'); }
}

function applyTheme(theme) {
  if (!['light','dark'].includes(theme)) theme = 'light';
  document.documentElement.dataset.theme = theme; document.documentElement.style.colorScheme = theme;
  $('themeIcon').textContent = theme==='dark'?'☀':'☾'; $('themeLabel').textContent = theme==='dark'?'Chế độ sáng':'Chế độ tối';
  $('themeToggle').setAttribute('aria-pressed',String(theme==='dark'));
  $('themeToggle').setAttribute('aria-label',theme==='dark'?'Chuyển sang chế độ sáng':'Chuyển sang chế độ tối');
  document.querySelectorAll('[data-set-theme]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.setTheme===theme)));
}
function saveTheme(theme) { applyTheme(theme); writePreference('schoolguard-theme',theme); }
function updateLoginMode() {
  const demo = $('sourceMode').value==='demo'; $('serverField').hidden = demo; $('serverUrl').required = !demo;
  $('loginError').textContent = ''; $('password').value = ''; $('loginButton').textContent = demo?'Vào bản mẫu →':'Đăng nhập →';
}
function registerPage(name, renderer, options = {}) {
  if (!['camera','alerts'].includes(name) || typeof renderer!=='function') throw Error('Chỉ đăng ký trang camera hoặc alerts.');
  modules.set(name,{render:renderer,label:options.label || (name==='camera'?'Giám sát camera':'Lịch sử cảnh báo')}); refreshNav();
  return () => { if (modules.get(name)?.render !== renderer) return; modules.delete(name); refreshNav(); if (currentPage===name && token) navigate('dashboard'); };
}
window.SchoolGuard = Object.freeze({API, registerPage, navigate, getSession:()=>({username,mode,authenticated:!!token}), refreshDashboard});

// Explicit demo transport. Backend failures never switch to this data.
const demoCameras = [{id:'CAM-01',name:'Camera 01',zone_id:1,status:'online'}, {id:'CAM-02',name:'Camera 02',zone_id:2,status:'offline'}];
const demoZones = [{id:1,name:'Cổng trường'},{id:2,name:'Hành lang'}];
const demoAlerts = Array.from({length:9},(_,i)=>({id:109-i,camera_id:i%2?'CAM-02':'CAM-01',zone_name:i%2?'Hành lang':'Cổng trường',location:i%2?'Hành lang':'Cổng trường',timestamp:new Date(Date.now()-i*7*3600000).toISOString(),status:i<3?'Mới':i<5?'Đang xử lý':'Đã xử lý'}));
const demoEvents = Array.from({length:3},(_,i)=>({id:i+1,object_type:'Người',zone_name:i%2?'Hành lang':'Cổng trường',source_id:'Video mẫu',source_type:'video',occurred_at:new Date(Date.now()-i*3600000).toISOString()}));
async function demoRequest(path, options={}) {
  if (options.signal?.aborted) throw abortError();
  if (path==='/token') {
    const p=new URLSearchParams(options.body);
    if (!['admin','baove'].includes(p.get('username')) || p.get('password')!=='demo123') { const error=Error('Tài khoản bản mẫu: admin hoặc baove. Mật khẩu: demo123.'); error.status=401; throw error; }
    return {access_token:'local-demo-session',token_type:'bearer'};
  }
  if (!token) throw Error('Vui lòng đăng nhập.');
  const u=new URL(path,baseUrl), data=({'/api/alerts':demoAlerts,'/api/cameras':demoCameras,'/api/zones':demoZones,'/api/events':demoEvents})[u.pathname];
  if (data) return structuredClone(data.slice(Number(u.searchParams.get('skip')||0),Number(u.searchParams.get('skip')||0)+Number(u.searchParams.get('limit')||500)));
  if (/^\/api\/(alerts|events)\/\d+\/image$/.test(u.pathname)) {
    // Raster illustration, not a result generated from a user's video.
    const canvas=document.createElement('canvas'); canvas.width=800; canvas.height=450;
    const c=canvas.getContext('2d'); c.fillStyle='#102e35'; c.fillRect(0,0,800,450); c.fillStyle='#244b50'; c.fillRect(0,300,800,150); c.strokeStyle='#e9788b'; c.lineWidth=3; c.strokeRect(460,100,220,260); c.fillStyle='#b5d3d9'; c.font='22px sans-serif'; c.fillText('SCHOOLGUARD · ANH MINH HOA',30,50);
    return new Promise((resolve,reject)=>canvas.toBlob(blob=>blob?resolve(blob):reject(Error('Không tạo được ảnh mẫu.')),'image/png'));
  }
  throw Error('Chức năng này chưa có trong bản mẫu.');
}

$('sourceMode').onchange=updateLoginMode;
$('togglePassword').onclick=()=>{ const show=$('password').type==='password'; $('password').type=show?'text':'password'; $('togglePassword').textContent=show?'Ẩn':'Hiện'; $('togglePassword').setAttribute('aria-pressed',String(show)); $('togglePassword').setAttribute('aria-label',show?'Ẩn mật khẩu':'Hiện mật khẩu'); };
$('loginForm').onsubmit=async event=>{
  event.preventDefault(); if(loginBusy)return;
  const name=$('username').value.trim(), password=$('password').value;
  if(!name || !password){$('loginError').textContent='Vui lòng nhập tài khoản và mật khẩu.';return;}
  loginBusy=true; const version=++sessionVersion; $('loginButton').disabled=true; $('loginButton').textContent='Đang đăng nhập…'; $('loginError').textContent='';
  for(const id of ['sourceMode','serverUrl','username','password'])$(id).disabled=true;
  try {
    mode=$('sourceMode').value==='demo'?'demo':'backend'; baseUrl=mode==='demo'?'http://127.0.0.1:8000':validateBaseUrl($('serverUrl').value.trim());
    const next=await authenticate(name,password); if(version!==sessionVersion)return;
    token=next; username=name; $('password').value='';
    if(mode==='backend')writePreference('schoolguard-server',baseUrl);
    $('userLabel').textContent=username; $('avatar').textContent=username.slice(0,1).toUpperCase(); $('sourceBadge').textContent=mode==='demo'?'Dữ liệu mẫu':'Hệ thống';
    $('login').hidden=true; $('app').hidden=false;
    window.dispatchEvent(new CustomEvent('schoolguard:login',{detail:{username,mode}}));
    await navigate('dashboard'); $('pageTitle').focus();
  } catch(error) { if(version===sessionVersion){token=null;$('loginError').textContent=errorMessage(error);} }
  finally {loginBusy=false;for(const id of ['sourceMode','serverUrl','username','password','loginButton'])$(id).disabled=false;$('loginButton').textContent=$('sourceMode').value==='demo'?'Vào bản mẫu →':'Đăng nhập →';}
};
$('logout').onclick=()=>endSession();
$('menuButton').onclick=()=>setMenu($('menuButton').getAttribute('aria-expanded')!=='true');
$('menuBackdrop').onclick=()=>setMenu(false);
$('themeToggle').onclick=()=>saveTheme(document.documentElement.dataset.theme==='dark'?'light':'dark');
$('closeEvidence').onclick=closeEvidence;
$('connectionRetry').onclick=()=>{if(!refreshBusy){if(currentPage==='dashboard')refreshDashboard();else navigate('dashboard');}};
$('evidenceDialog').addEventListener('cancel',event=>{event.preventDefault();closeEvidence();});
document.addEventListener('keydown',event=>{
  if(event.key==='Escape')setMenu(false);
  const point=event.target.closest?.('[data-chart-day]');
  if(!point||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
  event.preventDefault();const points=[...document.querySelectorAll('[data-chart-day]')],index=points.indexOf(point);
  const next=event.key==='Home'?0:event.key==='End'?points.length-1:Math.max(0,Math.min(points.length-1,index+(event.key==='ArrowLeft'?-1:1)));
  points[next].focus();selectChartDay(points[next]);
});
window.addEventListener?.('offline',()=>{if(token&&mode==='backend')setConnection('offline','Dữ liệu trên màn hình có thể chưa được cập nhật.');});
window.addEventListener?.('online',()=>{if(token&&mode==='backend')setConnection('recheck','Đã có mạng. Bấm Thử lại để kiểm tra máy chủ.');});
document.addEventListener('click',event=>{
  const chart=event.target.closest('[data-chart-day]');if(chart){selectChartDay(chart);return;}
  const nav=event.target.closest('[data-page]'); if(nav){navigate(nav.dataset.page);return;}
  const theme=event.target.closest('[data-set-theme]'); if(theme){saveTheme(theme.dataset.setTheme);return;}
  const evidence=event.target.closest('[data-evidence-id]'); if(evidence){showEvidence(evidence.dataset.evidenceKind,evidence.dataset.evidenceId);return;}
  if(event.target.closest('#refresh') && !refreshBusy)refreshDashboard();
});
let theme=readPreference('schoolguard-theme','');
if(!['light','dark'].includes(theme))theme=window.matchMedia?.('(prefers-color-scheme: dark)').matches?'dark':'light';
applyTheme(theme);
try{$('serverUrl').value=validateBaseUrl(readPreference('schoolguard-server','http://127.0.0.1:8000'));}catch{$('serverUrl').value='http://127.0.0.1:8000';}
if(window.location?.protocol==='file:')$('sourceMode').value='demo';
updateLoginMode();
setMenu(false);
window.matchMedia?.('(max-width: 760px)').addEventListener?.('change', () => setMenu(false));
