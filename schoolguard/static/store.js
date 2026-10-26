'use strict';
const form = document.querySelector('#signup-form');
const signedIn = document.querySelector('#signed-in');
const formStatus = document.querySelector('#form-status');
const accountStatus = document.querySelector('#account-status');
const requestButton = document.querySelector('#request-pro');
let selected = 'free';
let signedInUser = null;
let paymentEnabled = false;
let pilotCheckoutEnabled = false;
let emailRequired = false;
let googleAvailable = null;

async function call(path, options = {}) {
  const response = await fetch('/api' + path, {
    credentials: 'same-origin',
    ...options,
    headers: {'Content-Type': 'application/json', ...(options.headers || {})}
  });
  let result;
  try { result = await response.json(); } catch { result = {}; }
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Không kết nối được LH25. Thử lại sau.');
  return result;
}

function selectPlan(plan) {
  selected = plan;
  document.querySelector('#selected-plan').textContent = plan === 'pro' ? 'PRO LOCAL' : 'FREE';
  document.querySelector('#signup-subtitle').textContent = googleAvailable === false && !signedInUser
    ? 'Đăng ký Google đang chờ cấu hình; chưa thể tạo tài khoản Free hay mua Pro trên trang này.'
    : signedInUser ? `Đang đăng nhập: ${signedInUser.display_name || signedInUser.email || signedInUser.username}`
    : plan === 'pro'
    ? `Tạo tài khoản Free trước. ${emailRequired ? 'Xác minh email, ' : ''}kết nối Telegram rồi mở “Gói của tôi” để ${paymentEnabled || pilotCheckoutEnabled ? 'thanh toán' : 'yêu cầu'} Pro.`
    : `Tạo tài khoản Free. ${emailRequired ? 'Xác minh email trước khi sử dụng. ' : ''}Bạn có thể nâng cấp Pro sau.`;
  if (signedInUser) accountStatus.textContent = plan === 'pro'
    ? `Nhấn “${paymentEnabled || pilotCheckoutEnabled ? 'Mua' : 'Yêu cầu'} Pro Local” bên dưới để tiếp tục.`
    : '';
}

window.addEventListener('lh25-google-status', event => {
  googleAvailable = event.detail.enabled;
  selectPlan(selected);
});

document.querySelectorAll('[data-select-plan]').forEach(link => {
  link.addEventListener('click', () => selectPlan(link.dataset.selectPlan));
});

async function refreshAccount() {
  try {
    signedInUser = await call('/me');
    form.hidden = true;
    signedIn.hidden = false;
    const googleHost = document.querySelector('#google-auth-host');
    if (googleHost) googleHost.hidden = true;
    document.querySelector('#signup-subtitle').textContent = `Đang đăng nhập: ${signedInUser.display_name || signedInUser.email || signedInUser.username}`;
    const plan = await call('/me/plan');
    if (plan.plan === 'pro_local' || plan.plan === 'admin') {
      requestButton.textContent = 'Xem gói hiện tại ↗';
      requestButton.dataset.currentPlan = 'active';
    } else if (plan.pending_order && plan.pending_order.amount_vnd !== plan.pro_price_vnd) {
      requestButton.disabled = true;
      requestButton.textContent = 'Đơn cũ · cần Admin từ chối';
      accountStatus.textContent = `Đơn đang chờ có giá cũ ${Number(plan.pending_order.amount_vnd).toLocaleString('vi-VN')}đ. Đừng trả theo link cũ; nhờ Admin từ chối để tạo đơn ${Number(plan.pro_price_vnd).toLocaleString('vi-VN')}đ mới.`;
    } else if (plan.pending_order?.checkout_url && pilotCheckoutEnabled) {
      requestButton.dataset.checkoutUrl = plan.pending_order.checkout_url;
      requestButton.textContent = 'Mở lại mã QR payOS ↗';
    } else if (plan.pending_order?.payment_order_code && !plan.pending_order.checkout_url) {
      requestButton.disabled = true;
      requestButton.textContent = 'Admin đang kiểm tra mã payOS';
      accountStatus.textContent = 'Link payOS chưa được xác nhận. Đừng tạo đơn mới hoặc chuyển khoản trước khi Admin gắn link.';
    } else if (plan.pending_order?.status === 'requested' && pilotCheckoutEnabled) {
      requestButton.textContent = 'Tạo mã QR payOS ↗';
    } else if (plan.pending_order) {
      requestButton.disabled = true;
      requestButton.textContent = 'Yêu cầu Pro đang chờ xử lý';
    } else if (paymentEnabled) {
      requestButton.textContent = 'Thanh toán Pro Local ↗';
    } else if (pilotCheckoutEnabled) {
      requestButton.textContent = 'Mua Pro · mở mã QR payOS ↗';
    }
  } catch (error) {
    if (!error.message.includes('đăng nhập')) {
      accountStatus.textContent = 'Không tải được thông tin tài khoản. Bạn vẫn có thể vào ứng dụng để kiểm tra.';
    }
  }
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  const button = form.querySelector('button[type=submit]');
  const values = Object.fromEntries(new FormData(form));
  values.consent = values.consent === 'on';
  formStatus.classList.remove('error');
  formStatus.textContent = 'Đang tạo tài khoản…';
  button.disabled = true;
  try {
    const result = await call('/register', {method:'POST', body: JSON.stringify(values)});
    formStatus.textContent = result.email_verification_required
      ? 'Tạo tài khoản thành công. Đang mở bước xác minh email…'
      : 'Tạo tài khoản thành công. Đang mở bước kết nối Telegram…';
    location.assign(result.email_verification_required ? '/#plan' : '/#telegram');
  } catch (error) {
    formStatus.classList.add('error');
    formStatus.textContent = error.message;
    button.disabled = false;
  }
});

requestButton.addEventListener('click', async () => {
  if (!signedInUser) return;
  if (requestButton.dataset.currentPlan === 'active') {
    location.href = '/#plan';
    return;
  }
  if (requestButton.dataset.checkoutUrl) {
    const url = new URL(requestButton.dataset.checkoutUrl);
    if (url.protocol !== 'https:' || url.hostname !== 'pay.payos.vn') {
      accountStatus.textContent = 'Liên kết thanh toán không hợp lệ.';
      return;
    }
    location.assign(url.href);
    return;
  }
  requestButton.disabled = true;
  accountStatus.classList.remove('error');
  accountStatus.textContent = paymentEnabled || pilotCheckoutEnabled ? 'Đang tạo mã QR payOS…' : 'Đang gửi yêu cầu Pro…';
  try {
    if (paymentEnabled) {
      const order = await call('/orders/pro-local/checkout', {method:'POST', body:'{}'});
      const url = new URL(order.checkout_url);
      if (url.protocol !== 'https:' || url.hostname !== 'pay.payos.vn') throw new Error('Liên kết thanh toán không hợp lệ.');
      location.assign(url.href);
    } else {
      const order = await call('/orders/pro-local', {method:'POST', body:'{}'});
      if (order.checkout_url) {
        const url = new URL(order.checkout_url);
        if (url.protocol !== 'https:' || url.hostname !== 'pay.payos.vn') throw new Error('Liên kết thanh toán không hợp lệ.');
        location.assign(url.href);
      } else {
        accountStatus.textContent = `${order.message} Mã yêu cầu: ${order.id.slice(0, 8)}. Đang mở chi tiết…`;
        location.assign('/#plan');
      }
    }
  } catch (error) {
    accountStatus.classList.add('error');
    accountStatus.textContent = error.message;
    requestButton.disabled = false;
  }
});

call('/commerce/status').then(status => {
  paymentEnabled = status.payment_enabled;
  pilotCheckoutEnabled = status.pilot_checkout_enabled;
  emailRequired = status.email_required;
  if (emailRequired) {
    document.querySelector('.signup-card>small').textContent = 'Sau khi đăng ký, hãy mở email xác minh (hiệu lực 30 phút) rồi kết nối Telegram. Không nhập mật khẩu email hoặc Telegram vào website.';
    document.querySelector('.start-copy>p').textContent = 'Điền thông tin để tạo tài khoản Free. Xác minh email, sau đó kết nối Telegram trước khi phân tích video. Bạn có thể nâng cấp Pro khi các bước này hoàn tất.';
  }
  if (paymentEnabled) {
    document.querySelector('.pricing .section-heading p').textContent = 'Thanh toán qua payOS chỉ được mở sau khi có tên miền, tài khoản và email xác minh.';
    document.querySelector('.price-footnote').textContent = 'Pro chỉ được kích hoạt khi LH25 nhận webhook thanh toán có chữ ký hợp lệ. AI có thể báo sai hoặc bỏ sót; đây không phải dịch vụ khẩn cấp được chứng nhận.';
    document.querySelector('[data-select-plan="pro"]').innerHTML = 'Đăng ký để thanh toán Pro <span aria-hidden="true">↗</span>';
    document.querySelector('.start-copy>p').textContent = 'Tạo tài khoản Free, xác minh email và kết nối Telegram. Sau đó thanh toán Pro qua payOS; hệ thống tự mở quyền khi nhận xác nhận hợp lệ.';
    document.querySelector('#signed-in>p').textContent = 'Bạn đã đăng nhập LH25. Kết nối Telegram và xác minh email trước khi thanh toán Pro.';
    document.querySelector('.start-check span:last-child').textContent = '✓ Pro tự mở sau khi payOS xác nhận giao dịch';
    const paymentAnswer = [...document.querySelectorAll('.faq-list details')].find(item => item.querySelector('summary')?.textContent.includes('Thanh toán Pro'));
    if (paymentAnswer) paymentAnswer.querySelector('p').textContent = 'Sau khi xác minh email và kết nối Telegram, bạn mở Gói của tôi để thanh toán qua payOS. LH25 chỉ mở Pro sau khi nhận xác nhận hợp lệ từ hệ thống thanh toán.';
  } else if (pilotCheckoutEnabled) {
    document.querySelector('.pricing .section-heading p').textContent = 'Bấm mua Pro để nhận ngay mã QR payOS. Đây là giao dịch thật; Admin sẽ đối soát và duyệt thủ công.';
    document.querySelector('.price-footnote').textContent = 'Mã QR mở trên trang payOS; giao dịch là tiền thật. Pro chỉ được cấp sau khi Admin đối chiếu payOS và duyệt. Chế độ localhost chỉ dùng để thử trên cùng máy, chưa phải dịch vụ công khai.';
    document.querySelector('#signed-in>p').textContent = 'Bấm mua để mở mã QR payOS. Sau khi thanh toán, quay lại Gói của tôi và báo cho Admin đối soát.';
    const paymentAnswer = [...document.querySelectorAll('.faq-list details')].find(item => item.querySelector('summary')?.textContent.includes('Thanh toán Pro'));
    if (paymentAnswer) paymentAnswer.querySelector('p').textContent = 'Sau khi đăng nhập, bấm Mua Pro để mở ngay mã QR trên trang payOS. Thanh toán thật bằng ứng dụng ngân hàng, rồi quay lại LH25 báo đã thanh toán. Admin kiểm tra giao dịch trong payOS trước khi mở Pro và gửi hướng dẫn qua email.';
  } else {
    const paymentAnswer = [...document.querySelectorAll('.faq-list details')].find(item => item.querySelector('summary')?.textContent.includes('Thanh toán Pro'));
    if (paymentAnswer) paymentAnswer.querySelector('p').textContent = 'Đăng nhập LH25, mở Gói của tôi và gửi yêu cầu Pro. Admin tạo link payOS riêng cho đơn rồi gắn vào LH25; chỉ mở link đó để thanh toán. Bạn báo đã thanh toán, Admin kiểm tra trong tài khoản payOS trước khi mở Pro. Nếu link chưa xuất hiện, đừng chuyển khoản.';
  }
  selectPlan(selected);
}).catch(() => {}).finally(() => {
  refreshAccount().finally(() => window.LH25StoreI18n?.apply());
});
