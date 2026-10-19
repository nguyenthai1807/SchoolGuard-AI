const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'), path=require('node:path'), vm=require('node:vm');
const root=path.resolve(__dirname,'../minhkhangfe1');
const script=fs.readFileSync(path.join(root,'script.js'),'utf8');
const html=fs.readFileSync(path.join(root,'index.html'),'utf8');

function harness(fetcher=async()=>{throw new TypeError('Offline');}, prefs={}){
  const elements=new Map(),buttons=[],choices=[],charts=[],storage={...prefs};
  class Element{
    constructor(id=''){this.id=id;this.value='';this.type='';this.hidden=false;this.open=false;this.textContent='';this.dataset={};this.style={};this.attributes={};this.classes=new Set();this.disabled=false;
      this.classList={add:n=>this.classes.add(n),remove:n=>this.classes.delete(n),toggle:(n,b)=>{if(b??!this.classes.has(n))this.classes.add(n);else this.classes.delete(n);}};
    }
    set innerHTML(value){this.html=value;
      for(const m of value.matchAll(/id="([^"]+)"/g))elements.set(m[1],new Element(m[1]));
      if(this.id==='content'){choices.length=0;charts.length=0;}
      for(const m of value.matchAll(/data-chart-day="([^"]+)" data-chart-label="([^"]+)" data-chart-count="([^"]+)"/g)){const b=new Element();b.dataset={chartDay:m[1],chartLabel:m[2],chartCount:m[3]};charts.push(b);}
      for(const m of value.matchAll(/data-set-theme="([^"]+)"/g)){const b=new Element();b.dataset.setTheme=m[1];choices.push(b);}
      for(const m of value.matchAll(/data-page="([^"]+)"/g)){const b=new Element();b.dataset.page=m[1];buttons.push(b);}
    }
    get innerHTML(){return this.html||'';}
    setAttribute(name,value){this.attributes[name]=String(value);}
    getAttribute(name){return this.attributes[name]??null;}
    focus(){}close(){this.open=false;}showModal(){this.open=true;}addEventListener(){}
  }
  for(const m of html.matchAll(/id="([^"]+)"/g))elements.set(m[1],new Element(m[1]));
  for(const m of html.matchAll(/data-page="([^"]+)"/g)){const b=new Element();b.dataset.page=m[1];buttons.push(b);}
  elements.get('sourceMode').value='backend';elements.get('serverUrl').value='http://127.0.0.1:8000';
  const document={documentElement:new Element('root'),getElementById:id=>elements.get(id)||null,querySelectorAll:s=>s==='[data-set-theme]'?choices:s==='[data-page]'?buttons:s==='[data-chart-day]'?charts:[],addEventListener(){},
    createElement:()=>({width:0,height:0,getContext:()=>({fillRect(){},strokeRect(){},fillText(){}}),toBlob:cb=>cb(new Blob(['demo'],{type:'image/png'}))})};
  const timers=new Set();
  const context=vm.createContext({document,window:{matchMedia:()=>({matches:false}),dispatchEvent(){}},localStorage:{getItem:k=>storage[k]??null,setItem:(k,v)=>storage[k]=v},URL,URLSearchParams,Headers,Response,Blob,DOMException,CustomEvent,AbortController,structuredClone,console,
    fetch:fetcher,setTimeout:(fn,ms)=>{const id=setTimeout(()=>{timers.delete(id);fn();},ms);timers.add(id);return id;},clearTimeout:id=>{clearTimeout(id);timers.delete(id);}});
  vm.runInContext(script,context);
  return {context,elements,storage,document,run:source=>vm.runInContext(source,context),close(){timers.forEach(clearTimeout);}};
}
const json=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});
const camera={id:'CAM-01',name:'Cổng trường',zone_id:1,status:'online'};
const alert=i=>({id:i,camera_id:'CAM-01',zone_name:'Cổng trường',timestamp:'2026-10-19T00:00:00+07:00',status:'Mới'});
const event={id:1,zone_name:'Cổng trường',object_type:'Người',occurred_at:'2026-10-19T00:00:00+07:00'};
function apiFixture(url,options){const u=new URL(url);if(u.pathname==='/token')return json({access_token:'backend-token',token_type:'bearer'});return json(u.pathname==='/api/alerts'?[alert(1)]:u.pathname==='/api/cameras'?[camera]:u.pathname==='/api/zones'?[{id:1,name:'Cổng trường'}]:u.pathname==='/api/events'?[event]:[]);}

test('Three separate assets, no invented auth/summary routes, no token storage',()=>{
  new vm.Script(script);assert.match(html,/href="style.css"/);assert.match(html,/src="script.js"/);
  assert.doesNotMatch(script,/\/api\/auth|\/dashboard\/summary/);
  assert.doesNotMatch(script,/localStorage\.setItem\([^\n]*(?:token|password)/i);
  assert.doesNotMatch(html,/data-page="camera"|data-page="alerts"/);
});
test('BE2 login is form-urlencoded, token is only attached to protected requests',async()=>{
  const calls=[];const h=harness(async(url,o)=>{calls.push({url,o});return apiFixture(url,o);});
  try{await h.run("authenticate('admin','pass & +?')");assert.equal(calls[0].url,'http://127.0.0.1:8000/token');assert.equal(calls[0].o.method,'POST');assert.equal(new URLSearchParams(calls[0].o.body).get('password'),'pass & +?');assert.equal(calls[0].o.headers.get('Authorization'),null);
    h.run("token='private-token';");await h.run("API.get('/api/cameras')");assert.equal(calls[1].o.headers.get('Authorization'),'Bearer private-token');assert.equal(calls[1].o.credentials,'omit');
  }finally{h.close();}
});
test('Wrong login, missing token and schema errors are explicit',async()=>{
  const h=harness(async()=>json({detail:'Sai tài khoản'},401));try{await assert.rejects(h.run("authenticate('admin','wrong')"),/Sai tài khoản/);}finally{h.close();}
  const m=harness(async()=>json({user:{name:'Someone'}}));try{await assert.rejects(m.run("authenticate('admin','wrong')"),/Bearer/);}finally{m.close();}
  const s=harness(async()=>json({items:[]}));try{await assert.rejects(s.run("loadList('cameras')"),/cấu trúc/);}finally{s.close();}
});
test('Backend outage never falls back to demo',async()=>{
  const h=harness();try{await assert.rejects(h.run("API.get('/api/alerts')"),/Không kết nối/);assert.equal(h.run('mode'),'backend');}finally{h.close();}
});
test('Pagination loads all 501 alerts, not only the first 500',async()=>{
  const skips=[];const h=harness(async url=>{const u=new URL(url),skip=Number(u.searchParams.get('skip'));skips.push(skip);return json(Array.from({length:skip===0?500:1},(_,i)=>alert(skip+i+1)));});
  try{const rows=await h.run("loadList('alerts')");assert.equal(rows.length,501);assert.deepEqual(skips,[0,500]);}finally{h.close();}
});
test('Pagination loop and duplicate page are detected',async()=>{
  const rows=Array.from({length:500},(_,i)=>alert(i));const h=harness(async()=>json(rows));try{await assert.rejects(h.run("loadList('alerts')"),/cùng một trang/);}finally{h.close();}
});
test('Status/date mapping and online camera counts match actual schema',()=>{
  const h=harness();try{h.context.rows=[{...alert(1),status:'Mới'},{...alert(2),status:'Đang xử lý'},{...alert(3),status:'Đã xử lý'},{...alert(4),status:'Unknown'}];h.context.cams=[camera,{...camera,id:'CAM-02',status:'offline'}];
    const s=h.run('summarize(rows,cams,new Date("2026-10-19T00:00:00+07:00"))');assert.equal(s.total,4);assert.equal(s.active,1);assert.deepEqual({...s.counts},{new:1,processing:1,resolved:1,other:1});assert.equal(s.days.length,7);
  }finally{h.close();}
});
test('Dashboard renders actual BE2 arrays and labels AI events separately',async()=>{
  const h=harness(async(u,o)=>apiFixture(u,o));try{h.run("token='valid';username='admin';");await h.run("navigate('dashboard')");const markup=h.elements.get('content').innerHTML;assert.match(markup,/Cổng trường/);assert.match(markup,/Sự kiện nhận diện gần đây/);assert.match(markup,/#1/);assert.equal(h.elements.get('content').attributes['aria-busy'],'false');}finally{h.close();}
});
test('Empty data shows real zero; failed alerts show error instead of fake zero',async()=>{
  const h=harness(async()=>json([]));try{h.run("token='valid';");await h.run("navigate('dashboard')");assert.match(h.elements.get('content').innerHTML,/Chưa có cảnh báo/);assert.match(h.elements.get('content').innerHTML,/class="metric">0/);}finally{h.close();}
  const f=harness(async u=>new URL(u).pathname==='/api/alerts'?json({detail:'DB unavailable'},500):json([]));try{f.run("token='valid'");await f.run("navigate('dashboard')");const markup=f.elements.get('content').innerHTML;assert.match(markup,/Không tải được cảnh báo/);assert.match(markup,/class="metric">—/);assert.match(f.elements.get('lastSync').textContent,/một phần/);}finally{f.close();}
});
test('401 clears current session; a late old 401 cannot clear a new session',async()=>{
  const h=harness(async()=>json({detail:'Expired'},401));try{h.run("token='old'");await assert.rejects(h.run("API.get('/api/cameras')"));assert.equal(h.run('token'),null);assert.match(h.elements.get('loginError').textContent,/hết hạn/);}finally{h.close();}
  let finish;const late=harness(()=>new Promise(r=>finish=r));try{late.run("token='old'");const pending=late.run("API.get('/api/cameras')");late.run("token='new';sessionVersion++;");finish(json({detail:'Expired'},401));await assert.rejects(pending);assert.equal(late.run('token'),'new');}finally{late.close();}
});
test('Abort and timeout terminate fetch with the right errors',async()=>{
  const h=harness((u,o)=>new Promise((r,j)=>o.signal.addEventListener('abort',()=>j(new DOMException('Aborted','AbortError')))));try{
    await assert.rejects(h.run("API.get('/api/cameras',{timeout:5})"),/quá chậm/);
    h.run('testController=new AbortController()');const pending=h.run("API.get('/api/cameras',{signal:testController.signal})");h.run('testController.abort()');await assert.rejects(pending,e=>e.name==='AbortError');
  }finally{h.close();}
});
test('Stale refresh cannot overwrite newer data after navigation',async()=>{
  const waiting=[];const h=harness((u,o)=>new Promise(r=>waiting.push(()=>r(apiFixture(u,o)))));try{
    h.run("token='valid';");const pending=h.run("navigate('dashboard')");await h.run("navigate('settings')");waiting.forEach(f=>f());await pending;assert.match(h.elements.get('content').innerHTML,/Giao diện làm việc/);assert.doesNotMatch(h.elements.get('content').innerHTML,/Cảnh báo gần đây/);
  }finally{h.close();}
});
test('Cross-origin endpoint paths are rejected before credentials can leak',async()=>{
  const h=harness();try{for(const p of ['https://evil.invalid','//evil.invalid','/\\evil.invalid']){h.context.badPath=p;await assert.rejects(h.run('API.get(badPath)'),/không hợp lệ|máy chủ khác/);}}finally{h.close();}
});
test('Theme persists, invalid preference recovers, and blocked storage is tolerated',()=>{
  const h=harness(undefined,{'schoolguard-theme':'dark'});try{assert.equal(h.document.documentElement.dataset.theme,'dark');h.run("saveTheme('light')");assert.equal(h.storage['schoolguard-theme'],'light');h.run("localStorage.setItem=()=>{throw Error('blocked')};saveTheme('dark')");assert.equal(h.document.documentElement.dataset.theme,'dark');}finally{h.close();}
});
test('FE2/FE3 modules register separately and clean up on navigation',async()=>{
  const h=harness();try{h.run("token='valid';cleanupCount=0;window.SchoolGuard.registerPage('camera',async element=>{element.innerHTML='CAMERA MODULE';return()=>cleanupCount++;});");await h.run("navigate('camera')");assert.match(h.elements.get('moduleMount').innerHTML,/CAMERA MODULE/);await h.run("navigate('settings')");assert.equal(h.run('cleanupCount'),1);assert.equal(h.run("window.SchoolGuard.getSession().authenticated"),true);assert.equal(h.run("'token' in window.SchoolGuard.getSession()"),false);}finally{h.close();}
});
test('Demo only activates explicitly; local logout sends no invented endpoint',async()=>{
  const h=harness(()=>{throw Error('Demo must not fetch');});try{h.run("mode='demo';");await assert.rejects(h.run("authenticate('admin','bad')"));const t=await h.run("authenticate('admin','demo123')");h.context.t=t;h.run("token=t;username='admin'");await h.run("navigate('dashboard')");assert.match(h.elements.get('content').innerHTML,/DỮ LIỆU MẪU/);h.run('endSession()');assert.equal(h.run('token'),null);}finally{h.close();}
});
test('Evidence request includes Bearer; error/wrong media is rejected',async()=>{
  let auth;const h=harness(async(u,o)=>{auth=o.headers.get('Authorization');return new Response('bytes',{headers:{'Content-Type':'image/png'}});});try{h.run("token='private'");const blob=await h.run("API.get('/api/alerts/1/image',{image:true})");assert.equal(blob.type,'image/png');assert.equal(auth,'Bearer private');}finally{h.close();}
  const f=harness(async()=>new Response('<html>',{headers:{'Content-Type':'text/html'}}));try{await assert.rejects(f.run("API.get('/api/alerts/1/image',{image:true})"),/ảnh hợp lệ/);}finally{f.close();}
});
test('Untrusted names and status values are escaped',()=>{
  const h=harness();try{h.context.alerts=[{...alert(1),zone_name:'<img src=x onerror=alert(1)>',status:'<script>bad</script>'}];const markup=h.run('alertRows(alerts,[])');assert.doesNotMatch(markup,/<script>|<img src=x/);assert.match(markup,/&lt;img/);}finally{h.close();}
});
test('Actual login form handler recovers from a bad password and allows login/logout/login',async()=>{
  const calls=[];const h=harness(async(u,o)=>{calls.push(new URL(u).pathname);if(new URL(u).pathname==='/token'&&new URLSearchParams(o.body).get('password')==='wrong')return json({detail:'Sai tài khoản hoặc mật khẩu'},401);return apiFixture(u,o);});
  try{
    h.elements.get('username').value='admin';h.elements.get('password').value='wrong';
    await h.elements.get('loginForm').onsubmit({preventDefault(){}});
    assert.equal(h.elements.get('loginButton').disabled,false);assert.equal(h.elements.get('username').disabled,false);assert.match(h.elements.get('loginError').textContent,/Sai tài khoản/);
    h.elements.get('password').value='123456';await h.elements.get('loginForm').onsubmit({preventDefault(){}});
    assert.equal(h.elements.get('app').hidden,false);assert.equal(h.run('username'),'admin');assert.equal(h.elements.get('password').value,'');
    h.elements.get('logout').onclick();assert.equal(h.elements.get('app').hidden,true);assert.equal(h.run('token'),null);
    h.elements.get('password').value='123456';await h.elements.get('loginForm').onsubmit({preventDefault(){}});assert.equal(h.elements.get('app').hidden,false);
    assert.ok(!calls.some(p=>p.includes('/auth/')));
  }finally{h.close();}
});
test('Password show/hide and mobile menu controls update accessibility state',()=>{
  const h=harness();try{
    h.elements.get('password').type='password';h.elements.get('togglePassword').onclick();assert.equal(h.elements.get('password').type,'text');assert.equal(h.elements.get('togglePassword').attributes['aria-pressed'],'true');
    h.elements.get('togglePassword').onclick();assert.equal(h.elements.get('password').type,'password');
    h.elements.get('menuButton').onclick();assert.equal(h.elements.get('menuBackdrop').hidden,false);assert.equal(h.elements.get('menuButton').attributes['aria-expanded'],'true');h.elements.get('menuBackdrop').onclick();assert.equal(h.elements.get('menuBackdrop').hidden,true);
  }finally{h.close();}
});
test('Skeleton is visible during a pending load and cleared after the response',async()=>{
  const pending=[];const h=harness((u,o)=>new Promise(r=>pending.push(()=>r(apiFixture(u,o)))));try{
    h.run("token='valid'");const loaded=h.run("navigate('dashboard')");assert.match(h.elements.get('content').innerHTML,/dashboard-skeleton/);assert.equal(h.elements.get('content').attributes['aria-busy'],'true');assert.equal(h.elements.get('connectionStatus').dataset.state,'loading');
    pending.forEach(f=>f());await loaded;assert.doesNotMatch(h.elements.get('content').innerHTML,/dashboard-skeleton/);assert.equal(h.elements.get('connectionStatus').dataset.state,'connected');assert.equal(h.elements.get('connectionRetry').disabled,false);
  }finally{h.close();}
});
test('Interactive seven-day chart selects real counts including zero without fabricated trends',()=>{
  const h=harness();try{
    const markup=h.run("renderActivityChart([{date:'2026-10-18',label:'18/10',count:0},{date:'2026-10-19',label:'19/10',count:3}])");assert.match(markup,/18\/10: 0 cảnh báo/);assert.doesNotMatch(markup,/NaN|Infinity/);assert.match(markup,/chart-tooltip/);assert.match(markup,/3<\/b> cảnh báo/);
    h.elements.get('content').innerHTML=markup;h.run("selectChartDay(document.querySelectorAll('[data-chart-day]')[0])");assert.equal(h.elements.get('chartSelection').textContent,'18/10 · 0 cảnh báo');assert.equal(h.run('selectedChartDay'),'2026-10-18');
  }finally{h.close();}
});
test('Failed refresh retains last real dashboard and a retry restores connected state',async()=>{
  let fail=false;const h=harness(async(u,o)=>fail?json({detail:'Temporary outage'},503):apiFixture(u,o));try{
    h.run("token='valid'");await h.run("navigate('dashboard')");const markup=h.elements.get('content').innerHTML;
    fail=true;await h.run('refreshDashboard()');assert.equal(h.elements.get('content').innerHTML,markup);assert.equal(h.elements.get('content').classes.has('data-stale'),true);assert.equal(h.elements.get('connectionStatus').dataset.state,'error');assert.match(h.elements.get('connectionMessage').textContent,/lần cập nhật trước/);assert.equal(h.elements.get('refresh').disabled,false);
    fail=false;await h.run('refreshDashboard()');assert.equal(h.elements.get('connectionStatus').dataset.state,'connected');assert.equal(h.elements.get('content').classes.has('data-stale'),false);
  }finally{h.close();}
});
test('First-load failure is an error rather than permanent skeleton, partial/demo status is explicit',async()=>{
  const h=harness(async()=>json({detail:'Down'},503));try{h.run("token='valid'");await h.run("navigate('dashboard')");assert.doesNotMatch(h.elements.get('content').innerHTML,/dashboard-skeleton/);assert.equal(h.elements.get('connectionStatus').dataset.state,'error');assert.match(h.elements.get('content').innerHTML,/Không tải được/);}finally{h.close();}
  const d=harness();try{d.run("mode='demo';token='demo'");await d.run("navigate('dashboard')");assert.equal(d.elements.get('connectionStatus').dataset.state,'demo');assert.equal(d.elements.get('connectionRetry').hidden,true);}finally{d.close();}
});
