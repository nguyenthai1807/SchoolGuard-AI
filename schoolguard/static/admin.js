'use strict';
const byId=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const money=value=>Number(value||0).toLocaleString('vi-VN')+' ₫';
const date=value=>value?new Date(value).toLocaleString('vi-VN'):'—';
const readinessRows=items=>items.map(item=>`<div class="ops-check"><div><strong>${esc(item.label)}</strong><small>${esc(item.next_step||'')}</small></div><span class="ops-state ${item.ok===true?'ready':item.ok===null?'unknown':'missing'}">${item.ok===true?'Có cấu hình':item.ok===null?'Chưa kiểm tra':'Cần hoàn tất'}</span></div>`).join('');
async function api(path,options={}){
  const response=await fetch('/api'+path,{credentials:'same-origin',cache:'no-store',...options});
  const data=await response.json().catch(()=>({}));
  if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:response.status===401?'Phiên đăng nhập đã hết hạn. Vào ứng dụng và đăng nhập lại.':response.status===403?'Tài khoản này không có quyền Admin.':'Không tải được dữ liệu quản trị.');
  return data;
}
async function load(){
  byId('refresh').disabled=true;byId('message').textContent='Đang cập nhật…';
  try{
    const [me,users,orders,alerts,commerce,release,receipts]=await Promise.all([api('/me'),api('/users'),api('/admin/orders'),api('/alerts?status=false_positive&limit=100'),api('/commerce/status'),api('/admin/release-readiness'),api('/admin/billing-notifications')]);
    if(me.role!=='admin')throw new Error('Tài khoản này không có quyền Admin.');
    byId('release-state').textContent=release.production_ready?'SẴN SÀNG CÔNG KHAI':'CHỈ THỬ NGHIỆM CỤC BỘ';
    byId('release-note').textContent=release.note;
    byId('local-checks').innerHTML=readinessRows(release.local_checks||[]);
    byId('release-checks').innerHTML=readinessRows(release.checks);
    const receiptLabels={delivered:'Đã gửi',pending:'Đang chờ gửi lại',processing:'Đang gửi',failed:'Gửi thất bại'};
    byId('receipts').innerHTML=receipts.map(item=>`<div class="review"><strong>${esc(item.order_id.slice(0,8))} · ${esc(item.channel)}</strong><span>${esc(receiptLabels[item.status]||item.status)} · ${item.attempts} lần gửi</span></div>`).join('')||'<p class="hint">Chưa có thông báo thanh toán.</p>';
    const free=users.filter(user=>user.plan==='free').length,pro=users.filter(user=>user.plan==='pro_local').length;
    byId('free-count').textContent=free;byId('pro-count').textContent=pro;
    byId('pending-count').textContent=orders.filter(order=>['requested','transfer_reported','initiating','payment_pending'].includes(order.status)).length;
    byId('false-count').textContent=alerts.total;
    byId('user-count').textContent=users.length+' tài khoản';
    byId('payment-mode').textContent=commerce.payment_enabled?'PAYOS TỰ ĐỘNG':'PAYOS LINK · DUYỆT TAY';
    byId('billing-hint').textContent=commerce.payment_enabled
      ?'payOS chỉ mở Pro sau webhook hợp lệ; không xác nhận thủ công ở chế độ này.'
      :'Với link tạo tự động trên localhost, mã và số tiền đã gắn với đơn. Nếu chưa có link, Admin có thể tạo riêng trong my.payos.vn. Chỉ bấm duyệt khi giao dịch hiện Đã thanh toán trong payOS và khớp mã đơn. Đơn giá cũ chưa trả: hủy link cũ trong payOS trước khi từ chối tại LH25; khách sẽ tạo đơn mới 29.000đ.';
    byId('users').innerHTML=users.map(user=>`<tr><td><strong>${esc(user.display_name||user.username)}</strong><small>${esc(user.username)}</small></td><td>${esc(user.email||'Chưa nhập')}${user.email_verified?' ✓':''}</td><td><span class="state">${user.plan==='admin'?'Admin':user.plan==='pro_local'?'Pro':'Free'}</span></td><td>${esc(date(user.expires_at))}</td><td>${user.telegram_linked?'Đã kết nối':'Chưa kết nối'}</td></tr>`).join('')||'<tr><td colspan="5">Chưa có tài khoản.</td></tr>';
    const labels={requested:'Chờ khách chuyển khoản',transfer_reported:'Khách báo đã chuyển · cần đối soát',initiating:'Đang tạo thanh toán',payment_pending:'Chờ payOS',activated:'Đã mở Pro',rejected:'Từ chối',checkout_failed:'Lỗi tạo thanh toán'};
    byId('orders').innerHTML=orders.map(order=>`<tr><td><strong>${esc(order.display_name||order.username)}</strong><small>${esc(order.email||'Chưa có email')} · ${esc(order.phone||'Chưa có SĐT')}</small></td><td><strong>${esc(order.id.slice(0,8))}</strong><small>LH25${esc(order.id.slice(0,12).toUpperCase())}</small></td><td>${money(order.amount_vnd)}</td><td><span class="state ${['requested','transfer_reported','initiating','payment_pending'].includes(order.status)?'pending':''}">${esc(labels[order.status]||order.status)}</span></td><td>${esc(date(order.created_at))}</td><td>${!commerce.payment_enabled&&['requested','transfer_reported'].includes(order.status)?`<form data-activate="${esc(order.id)}"><label>Mã giao dịch trên sao kê<input name="payment_reference" minlength="4" maxlength="120" required placeholder="Mã giao dịch thật"></label><button type="submit">Đã nhận tiền · mở Pro</button><button type="button" data-reject="${esc(order.id)}">Từ chối</button></form>`:order.status==='activated'?`<small>Mã giao dịch: ${esc(order.payment_reference||'—')}</small><button type="button" data-resend="${esc(order.id)}">Gửi lại hướng dẫn</button>`:'—'}</td></tr>`).join('')||'<tr><td colspan="6">Chưa có đơn hàng.</td></tr>';
    if(!commerce.payment_enabled)orders.forEach((order,index)=>{
      if(!['requested','transfer_reported'].includes(order.status))return;
      const cell=byId('orders').rows[index].cells[5];
      if(order.payment_order_code){
        byId('orders').rows[index].cells[1].querySelector('small').textContent='LH25'+String(order.payment_order_code).slice(-5);
      }
      const referenceLabel=cell.querySelector('form[data-activate] label');
      if(referenceLabel)referenceLabel.firstChild.textContent='Mã giao dịch trong payOS / sao kê';
      if(order.checkout_url){
        cell.insertAdjacentHTML('afterbegin',`<p><a data-payos-url href="${esc(order.checkout_url)}" target="_blank" rel="noopener noreferrer">Xem link payOS đã gắn ↗</a></p>`);
      }else{
        cell.insertAdjacentHTML('afterbegin',`<form data-link="${esc(order.id)}"><label>Link payOS cho riêng đơn này<input name="url" type="url" maxlength="512" required placeholder="https://pay.payos.vn/web/..."></label><button type="submit">Gắn link payOS</button></form>`);
      }
    });
    const reports=alerts.items.filter(alert=>alert.status==='false_positive');
    byId('reviews').innerHTML=reports.map(alert=>`<article class="review"><div><strong>${esc(alert.source_name)} · ${Number(alert.video_time).toFixed(1)}s</strong><small>${esc(alert.note||'Người dùng đã đánh dấu báo nhầm.')}</small></div><a href="/api/alerts/${encodeURIComponent(alert.id)}/evidence" target="_blank" rel="noopener">Xem bằng chứng ↗</a></article>`).join('')||'<p class="hint">Chưa có phản hồi báo nhầm trong 100 cảnh báo gần nhất.</p>';
    byId('message').textContent='Cập nhật lúc '+new Date().toLocaleTimeString('vi-VN')+' · Hiển thị phản hồi báo nhầm của các cảnh báo còn hỗ trợ.';
  }catch(error){byId('message').textContent=error.message;}
  finally{byId('refresh').disabled=false;}
}
byId('refresh').addEventListener('click',load);
byId('orders').addEventListener('click',async event=>{
  const reject=event.target.closest('[data-reject]');
  if(reject){
    if(!confirm('Từ chối đơn Pro này?'))return;
    reject.disabled=true;
    try{await api('/admin/orders/'+encodeURIComponent(reject.dataset.reject)+'/reject',{method:'POST'});await load();}
    catch(error){byId('message').textContent=error.message;reject.disabled=false;}
    return;
  }
  const button=event.target.closest('[data-resend]');if(!button)return;
  button.disabled=true;
  try{const result=await api('/admin/orders/'+encodeURIComponent(button.dataset.resend)+'/resend-guide',{method:'POST'});byId('message').textContent=result.note;}
  catch(error){byId('message').textContent=error.message;button.disabled=false;}
});
byId('orders').addEventListener('submit',async event=>{
  const linkForm=event.target.closest('[data-link]');
  if(linkForm){
    event.preventDefault();
    if(!confirm('Bạn đã tạo link riêng cho đúng đơn, đúng số tiền và mã LH25 này trong payOS?'))return;
    const button=linkForm.querySelector('button[type=submit]');button.disabled=true;
    try{await api('/admin/orders/'+encodeURIComponent(linkForm.dataset.link)+'/manual-payos-link',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:linkForm.elements.url.value.trim()})});await load();byId('message').textContent='Đã gắn link payOS cho đơn. Khách có thể mở link trong Gói của tôi.';}
    catch(error){byId('message').textContent=error.message;button.disabled=false;}
    return;
  }
  const form=event.target.closest('[data-activate]');if(!form)return;
  event.preventDefault();
  if(!confirm('Bạn đã thấy giao dịch Đã thanh toán trong tài khoản payOS (hoặc tiền đã ghi có trên sao kê) và khớp đúng số tiền, mã LH25, mã giao dịch thật?'))return;
  const button=form.querySelector('button[type=submit]');button.disabled=true;
  try{await api('/admin/orders/'+encodeURIComponent(form.dataset.activate)+'/activate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({payment_reference:form.elements.payment_reference.value.trim()})});await load();byId('message').textContent='Đã đối soát và mở Pro. Kiểm tra trạng thái gửi hướng dẫn ở bên dưới.';}
  catch(error){byId('message').textContent=error.message;button.disabled=false;}
});
load();
