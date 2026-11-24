import { initializeApp } from 'https://www.gstatic.com/firebasejs/13.1.0/firebase-app.js';
import { getAuth, GoogleAuthProvider, onAuthStateChanged, signInWithPopup, signOut } from 'https://www.gstatic.com/firebasejs/13.1.0/firebase-auth.js';
import { doc, getDoc, getFirestore, serverTimestamp, setDoc, updateDoc } from 'https://www.gstatic.com/firebasejs/13.1.0/firebase-firestore.js';

// Public Firebase web-app identifier. No payment credential is included here.
const APP_ID = '1:1012776114122:web:8d24980fc1b71bfe15a133';
const TERMS_VERSION = '2026-10-26-browser';
const element = (id) => document.getElementById(id);
const show = (id, visible) => { element(id).hidden = !visible; };
const message = (value) => { element('status').textContent = value; };

async function boot() {
  try {
    const response = await fetch('/__/firebase/init.json');
    if (!response.ok) throw new Error('Missing Firebase Hosting config');
    const config = await response.json();
    const app = initializeApp({ ...config, appId: APP_ID });
    const auth = getAuth(app);
    const db = getFirestore(app);
    let activeUser = null;
    let activeProfileExists = false;

    element('google-login').addEventListener('click', async () => {
      element('google-login').disabled = true;
      try {
        await signInWithPopup(auth, new GoogleAuthProvider());
      } catch (error) {
        const code = typeof error?.code === 'string' && /^auth\/[a-z-]+$/.test(error.code)
          ? error.code : 'unknown';
        message(code === 'auth/popup-closed-by-user'
          ? 'Bạn đã đóng cửa sổ Google.'
          : `Đăng nhập Google chưa thành công (${code}). Vui lòng thử lại.`);
      } finally {
        element('google-login').disabled = false;
      }
    });
    element('logout').addEventListener('click', () => { void signOut(auth); });
    element('accept-terms').addEventListener('change', () => {
      element('complete-register').disabled = !element('accept-terms').checked;
    });
    element('complete-register').addEventListener('click', async () => {
      const user = activeUser;
      if (!user || !user.emailVerified || !element('accept-terms').checked) return;
      element('complete-register').disabled = true;
      try {
        const ref = doc(db, 'users', user.uid);
        if (activeProfileExists) await updateDoc(ref, { acceptedTermsVersion: TERMS_VERSION });
        else await setDoc(ref, {
          email: user.email,
          displayName: (user.displayName || '').slice(0, 120),
          acceptedTermsVersion: TERMS_VERSION,
          createdAt: serverTimestamp(),
        });
        await render(user);
      } catch {
        message('Chưa tạo được tài khoản Free. Vui lòng thử lại.');
        element('complete-register').disabled = false;
      }
    });

    async function render(user) {
      activeUser = user;
      show('login-view', true);
      document.querySelector('.skip-link').href = '#login-view';
      show('signed-out', !user);
      show('register', false);
      show('dashboard', false);
      if (!user) return message('Đăng nhập Google để tiếp tục.');
      if (!user.emailVerified) return message('Google chưa xác minh email của tài khoản này.');
      message('Đang kiểm tra tài khoản…');
      try {
        const profile = await getDoc(doc(db, 'users', user.uid));
        if (activeUser?.uid !== user.uid) return;
        activeProfileExists = profile.exists();
        if (!profile.exists() || profile.data().acceptedTermsVersion !== TERMS_VERSION) {
          element('register-email').textContent = user.email || '';
          element('register-title').textContent = profile.exists()
            ? 'Xác nhận điều khoản phân tích trên thiết bị'
            : 'Hoàn tất tài khoản Free';
          element('complete-register').textContent = profile.exists()
            ? 'Đồng ý và mở phân tích Free'
            : 'Tạo tài khoản Free';
          element('accept-terms').checked = false;
          element('complete-register').disabled = true;
          show('register', true);
          return message('Đọc điều khoản cập nhật và xác nhận để dùng phân tích Free trên thiết bị.');
        }
        element('account-name').textContent = user.displayName || 'Khách LH25';
        element('account-email').textContent = user.email || '';
        show('login-view', false);
        show('dashboard', true);
        document.querySelector('.skip-link').href = '#content';
        message('Đã đăng nhập tài khoản Free.');
      } catch {
        message('Chưa truy cập được dữ liệu tài khoản. Vui lòng thử lại sau.');
      }
    }
    onAuthStateChanged(auth, (user) => { void render(user); });
  } catch {
    message('Cổng tài khoản chưa sẵn sàng. Không có dữ liệu hoặc thanh toán nào được gửi.');
  }
}

void boot();
