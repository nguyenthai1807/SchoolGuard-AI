import { initializeApp } from 'https://www.gstatic.com/firebasejs/13.1.0/firebase-app.js';
import { getAuth, onAuthStateChanged } from 'https://www.gstatic.com/firebasejs/13.1.0/firebase-auth.js';
import { doc, getDoc, getFirestore } from 'https://www.gstatic.com/firebasejs/13.1.0/firebase-firestore.js';

const APP_ID = '1:1012776114122:web:8d24980fc1b71bfe15a133';
const TERMS_VERSION = '2026-10-26-browser';
const gate = document.getElementById('gate-status');
let loaded = false;

try {
  const response = await fetch('/__/firebase/init.json');
  if (!response.ok) throw new Error('Firebase configuration unavailable');
  const app = initializeApp({ ...(await response.json()), appId: APP_ID });
  const db = getFirestore(app);
  onAuthStateChanged(getAuth(app), async (user) => {
    if (!user?.emailVerified) {
      document.getElementById('analysis').hidden = true;
      gate.textContent = 'Hãy đăng nhập Google và xác nhận điều khoản Free tại trang tài khoản LH25.';
      if (loaded) location.replace('/');
      return;
    }
    try {
      const profile = await getDoc(doc(db, 'users', user.uid));
      if (!profile.exists() || profile.data().acceptedTermsVersion !== TERMS_VERSION) {
        gate.textContent = 'Hãy xác nhận điều khoản phân tích trên thiết bị tại trang tài khoản LH25.';
        if (loaded) location.replace('/');
        return;
      }
      document.getElementById('analysis').hidden = false;
      gate.textContent = `Đã đăng nhập Free: ${user.email}. Video chỉ được phân tích trên thiết bị này.`;
      if (!loaded) {
        loaded = true;
        await import('/browser.js');
      }
    } catch {
      gate.textContent = 'Chưa kiểm tra được tài khoản Free. Vui lòng tải lại trang.';
    }
  });
} catch {
  gate.textContent = 'Bộ phân tích chưa sẵn sàng; không có video nào được gửi đi.';
}
