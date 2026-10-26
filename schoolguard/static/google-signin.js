'use strict';
(() => {
  const host = document.querySelector('.login-card') || document.querySelector('.signup-card');
  if (!host) return;
  const storeSignup = host.classList.contains('signup-card');
  const appLogin = Boolean(document.querySelector('#login'));
  const legacy = document.querySelector('#legacy-login');
  const panel = host.querySelector('#google-auth-host') || document.createElement('section');
  if (!panel.id) {
    panel.id = 'google-auth-host';
    panel.className = 'google-auth';
    const before = storeSignup ? document.querySelector('#signup-form') : host.querySelector('.login-store-link') || host.querySelector(':scope > a');
    host.insertBefore(panel, before);
  }
  const buttonSlot = panel.querySelector('.google-button-slot') || document.createElement('div');
  buttonSlot.classList.add('google-button-slot');
  buttonSlot.removeAttribute('aria-hidden');
  const message = panel.querySelector('[role="status"]') || document.createElement('p');
  message.setAttribute('role', 'status');
  message.setAttribute('aria-live', 'polite');
  let consent = null;
  let consentLabel = null;
  let terms = null;
  let confirmConsent = null;
  let pendingCredential = null;
  if (storeSignup) {
    // Ask for LH25 data consent only after Google identifies a new account.
    consentLabel = document.createElement('label');
    consentLabel.hidden = true;
    consent = document.createElement('input');
    consent.type = 'checkbox';
    consentLabel.append(consent, document.createTextNode(' Tôi đồng ý với điều khoản và chính sách dữ liệu LH25.'));
    terms = document.createElement('a');
    terms.hidden = true;
    terms.href = '/terms';
    terms.textContent = 'Đọc điều khoản và quyền riêng tư';
    confirmConsent = document.createElement('button');
    confirmConsent.type = 'button';
    confirmConsent.className = 'consent-confirm';
    confirmConsent.textContent = 'Đồng ý & tạo tài khoản Free';
    confirmConsent.hidden = true;
    panel.prepend(consentLabel, terms);
  }
  panel.append(buttonSlot, message);
  if (confirmConsent) panel.append(confirmConsent);
  message.textContent = 'Đang chuẩn bị đăng nhập Google…';
  let googleOnly = false;

  const fallback = (note, googleOnly = false) => {
    message.textContent = note;
    if (legacy && !googleOnly) legacy.hidden = false;
  };
  const authenticate = async (credential, acceptedConsent = false) => {
    message.textContent = acceptedConsent ? 'Đang tạo tài khoản LH25…' : 'Đang xác minh tài khoản Google…';
    buttonSlot.classList.add('is-busy');
    if (confirmConsent) confirmConsent.disabled = true;
    try {
      const resultResponse = await fetch('/api/auth/google', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({credential, consent: acceptedConsent})
      });
      const result = await resultResponse.json();
      if (!resultResponse.ok) {
        if (storeSignup && resultResponse.status === 409 &&
            result.detail === 'Đồng ý điều khoản dữ liệu trước khi tạo tài khoản.') {
          pendingCredential = credential;
          consentLabel.hidden = false;
          terms.hidden = false;
          confirmConsent.hidden = false;
          message.textContent = 'Đây là tài khoản mới. Đọc điều khoản và đồng ý để tạo tài khoản Free.';
          return;
        }
        throw new Error(typeof result.detail === 'string' ? result.detail : 'Đăng nhập thất bại.');
      }
      pendingCredential = null;
      if (host.dataset.requireAdmin === 'true' && result.role !== 'admin') {
        message.textContent = 'Tài khoản Google này chưa được cấp quyền Admin.';
        const denied = document.querySelector('#admin-denied');
        if (denied) denied.hidden = false;
        return;
      }
      if (appLogin) {
        message.textContent = 'Đã đăng nhập. Đang mở LH25…';
        window.dispatchEvent(new CustomEvent('lh25-google-authenticated', {detail: result}));
        return;
      }
      location.assign(host.dataset.redirect || '/#overview');
    } catch (error) {
      message.textContent = error.message;
      if (appLogin && /Đồng ý điều khoản dữ liệu trước khi tạo tài khoản/.test(error.message)) {
        const link = document.createElement('a');
        link.href = '/store#start';
        link.textContent = 'Tạo tài khoản Free tại STORE';
        message.append(' ', link);
      }
    } finally {
      buttonSlot.classList.remove('is-busy');
      if (confirmConsent) confirmConsent.disabled = false;
    }
  };
  if (confirmConsent) confirmConsent.addEventListener('click', () => {
    if (!consent.checked) {
      message.textContent = 'Hãy đánh dấu đồng ý điều khoản để tạo tài khoản.';
      consent.focus();
      return;
    }
    if (!pendingCredential) {
      message.textContent = 'Phiên Google đã hết. Hãy chọn Google lần nữa.';
      return;
    }
    authenticate(pendingCredential, true);
  });
  (async () => {
    try {
      const response = await fetch('/api/auth/google/config', {credentials: 'same-origin', cache: 'no-store'});
      if (!response.ok) throw new Error('Không kết nối được dịch vụ đăng nhập.');
      const config = await response.json();
      googleOnly = Boolean(config.google_only);
      window.dispatchEvent(new CustomEvent('lh25-google-status', {detail: {enabled: config.enabled}}));
      if (legacy) legacy.hidden = true;
      if (storeSignup) {
        const oldForm = document.querySelector('#signup-form');
        if (oldForm) oldForm.hidden = true;
        if (config.google_only) {
          const subtitle = document.querySelector('#signup-subtitle');
          if (subtitle) subtitle.textContent = 'Dùng tài khoản Google để bắt đầu Free. Sau đó kết nối Telegram trong ứng dụng.';
        }
      }
      if (!config.enabled) {
        fallback(storeSignup
          ? 'Đăng ký Google chưa mở trên máy chủ này. Hiện chưa nhận đăng ký hoặc thanh toán tại Store.'
          : 'Đăng nhập Google chưa được cấu hình trên máy chủ này.', config.google_only);
        if (storeSignup) {
          const free = document.querySelector('[data-select-plan="free"]');
          const pro = document.querySelector('[data-select-plan="pro"]');
          const hero = document.querySelector('.hero-actions .primary');
          if (free) free.textContent = 'Free · sắp mở';
          if (pro) pro.textContent = 'Pro · chưa mở bán';
          if (hero) hero.textContent = 'Xem trạng thái Free';
          window.LH25StoreI18n?.apply();
        }
        return;
      }
      if (location.hostname === '127.0.0.1') {
        const localUrl = new URL(location.href);
        localUrl.hostname = 'localhost';
        const link = document.createElement('a');
        link.href = localUrl.href;
        link.textContent = 'Mở bằng localhost để đăng nhập Google';
        message.textContent = 'Google chưa chấp nhận đăng nhập từ 127.0.0.1 trên máy này. ';
        message.append(link);
        return;
      }
      const script = document.createElement('script');
      script.src = 'https://accounts.google.com/gsi/client';
      script.async = true;
      const loaded = new Promise((resolve, reject) => {
        script.onload = resolve;
        script.onerror = () => reject(new Error('Không tải được nút Google. Hãy kiểm tra kết nối.'));
      });
      document.head.append(script);
      await Promise.race([
        loaded,
        new Promise((_, reject) => setTimeout(() => reject(new Error('Google phản hồi chậm. Hãy tải lại trang để thử lại.')), 15000))
      ]);
      google.accounts.id.initialize({
        client_id: config.client_id,
        nonce: config.nonce,
        auto_select: false,
        callback: ({credential}) => authenticate(credential)
      });
      google.accounts.id.renderButton(buttonSlot, {theme: 'outline', size: 'large', text: 'continue_with'});
      if (storeSignup) {
        message.textContent = 'Đã có tài khoản? Đăng nhập ngay. Tài khoản mới sẽ được hỏi điều khoản ở bước tiếp theo.';
      } else {
        message.textContent = 'Dùng tài khoản Google đã liên kết với LH25.';
      }
    } catch (error) {
      fallback(error.message, googleOnly);
      window.dispatchEvent(new CustomEvent('lh25-google-status', {detail: {enabled: false}}));
    }
  })();
})();
