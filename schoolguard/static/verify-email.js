'use strict';
(async () => {
  const status = document.querySelector('#verify-status');
  const token = new URLSearchParams(location.hash.slice(1)).get('token');
  history.replaceState(null, '', '/verify-email');
  if (!token) {
    status.textContent = 'Thiếu mã xác minh. Mở lại liên kết trong email hoặc gửi lại từ mục Gói của tôi.';
    return;
  }
  try {
    const response = await fetch('/api/email/verify', {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({token})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Không xác minh được email.');
    status.textContent = 'Email đã được xác minh. Bạn có thể tiếp tục kết nối Telegram và sử dụng LH25.';
  } catch (error) {
    status.textContent = error.message + ' Hãy gửi lại email trong mục Gói của tôi.';
  }
})();
