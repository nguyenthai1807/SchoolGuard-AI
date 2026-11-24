import { initializeApp } from 'https://www.gstatic.com/firebasejs/13.1.0/firebase-app.js';
import { getAuth, GoogleAuthProvider, onAuthStateChanged, signInWithPopup, signOut } from 'https://www.gstatic.com/firebasejs/13.1.0/firebase-auth.js';
import { addDoc, collection, doc, getDoc, getFirestore, onSnapshot, query, runTransaction, serverTimestamp, setDoc, Timestamp, updateDoc, where } from 'https://www.gstatic.com/firebasejs/13.1.0/firebase-firestore.js';

// Staged manual-commerce design; not deployed to the public Free account site.
// This ID and /__/firebase/init.json are public client configuration, never payOS credentials.
const FIREBASE_APP_ID = '1:1012776114122:web:8d24980fc1b71bfe15a133';
const PRICE = 29000;
const TERM_VERSION = '2026-10-25';
const DAY_MS = 86400000;
const $ = (id) => document.getElementById(id);
const show = (id, visible) => { $(id).hidden = !visible; };
const status = (message) => { $('status').textContent = message; };
let auth;
let db;
let currentUser;
let stopMyOrders;
let stopAdminOrders;
let stopEntitlement;
let hasOpenOrder = false;

function trustedPayosUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && url.hostname === 'pay.payos.vn' && url.pathname.startsWith('/web/');
  } catch {
    return false;
  }
}

function orderTime(value) {
  return value?.toDate?.()?.toLocaleString('vi-VN') ?? 'Đang cập nhật';
}

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function renderMyOrders(items) {
  const list = $('my-orders');
  list.replaceChildren();
  hasOpenOrder = items.some(({ data }) => ['requested', 'link_ready'].includes(data.status));
  $('request-pro').disabled = hasOpenOrder;
  if (!items.length) {
    list.append(node('p', 'Bạn chưa có yêu cầu Pro.'));
    return;
  }
  items.sort((a, b) => (b.data.createdAt?.toMillis?.() ?? 0) - (a.data.createdAt?.toMillis?.() ?? 0));
  for (const { id, data } of items) {
    const card = node('article', undefined, 'order');
    card.append(node('strong', `Đơn ${id.slice(0, 8)} · ${Number(data.amount).toLocaleString('vi-VN')}₫`));
    card.append(node('p', `${orderTime(data.createdAt)} · ${data.status === 'paid' ? 'Đã mở Pro' : data.status === 'link_ready' ? 'Đã có link payOS' : 'Đang chờ Admin'}`));
    if (data.status === 'link_ready' && trustedPayosUrl(data.checkoutUrl)) {
      const link = node('a', 'Mở trang thanh toán payOS ↗');
      link.href = data.checkoutUrl;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      card.append(link);
      card.append(node('p', 'Sau khi chuyển khoản, chờ Admin đối soát. Việc mở link hoặc quay lại trang không tự mở Pro.'));
    }
    list.append(card);
  }
}

function watchCustomer(uid) {
  stopMyOrders?.();
  stopEntitlement?.();
  const mine = query(collection(db, 'orders'), where('uid', '==', uid));
  stopMyOrders = onSnapshot(mine, (snapshot) => {
    renderMyOrders(snapshot.docs.map((item) => ({ id: item.id, data: item.data() })));
  }, () => status('Không đọc được đơn hàng. Vui lòng thử lại.'));
  stopEntitlement = onSnapshot(doc(db, 'entitlements', uid), (snapshot) => {
    const entitlement = snapshot.data();
    const active = entitlement?.plan === 'pro' && entitlement?.validUntil?.toMillis?.() > Date.now();
    $('plan-name').textContent = active ? 'Pro' : 'Free';
    $('plan-detail').textContent = active
      ? `Có hiệu lực đến ${orderTime(entitlement.validUntil)}. Chỉ tính năng Pro đã phát hành mới được mở.`
      : 'Quyền Pro chỉ được mở sau khi Admin xác minh giao dịch thật.';
  }, () => status('Không đọc được trạng thái gói. Vui lòng thử lại.'));
}

function adminOrderCard(id, data) {
  const card = node('article', undefined, 'order');
  card.append(node('strong', `Đơn ${id} · ${data.email ?? ''}`));
  card.append(node('p', `${data.status} · ${Number(data.amount).toLocaleString('vi-VN')}₫ · ${orderTime(data.createdAt)}`));
  if (data.status === 'paid') return card;
  const actions = node('div', undefined, 'order-actions');
  const linkInput = node('input');
  linkInput.type = 'url';
  linkInput.placeholder = 'https://pay.payos.vn/web/...';
  linkInput.setAttribute('aria-label', `Link payOS cho đơn ${id}`);
  linkInput.value = data.checkoutUrl ?? '';
  const attach = node('button', 'Gắn link payOS');
  attach.type = 'button';
  attach.addEventListener('click', async () => {
    if (!trustedPayosUrl(linkInput.value)) return status('Link phải là https://pay.payos.vn/web/...');
    attach.disabled = true;
    try {
      await updateDoc(doc(db, 'orders', id), { checkoutUrl: linkInput.value, status: 'link_ready' });
      status(`Đã gắn link cho đơn ${id}.`);
    } catch {
      status('Không lưu được link payOS.');
      attach.disabled = false;
    }
  });
  actions.append(linkInput, attach);
  const reference = node('input');
  reference.type = 'text';
  reference.placeholder = 'Mã giao dịch đã đối soát trong payOS';
  reference.setAttribute('aria-label', `Mã giao dịch cho đơn ${id}`);
  const approve = node('button', 'Đã nhận tiền · mở Pro');
  approve.type = 'button';
  approve.disabled = data.status !== 'link_ready';
  approve.addEventListener('click', async () => {
    const bankRef = reference.value.trim();
    if (bankRef.length < 6 || bankRef.length > 120) return status('Nhập mã giao dịch hợp lệ đã đối soát trong payOS.');
    if (!window.confirm(`Bạn đã kiểm tra giao dịch THÀNH CÔNG tại payOS, đúng 29.000₫ và đúng đơn ${id}?`)) return;
    approve.disabled = true;
    try {
      const bytes = new TextEncoder().encode(bankRef);
      const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map((byte) => byte.toString(16).padStart(2, '0')).join('');
      await runTransaction(db, async (tx) => {
        const orderRef = doc(db, 'orders', id);
        const paymentRef = doc(db, 'paymentRefs', hash);
        const entitlementRef = doc(db, 'entitlements', data.uid);
        const order = await tx.get(orderRef);
        const used = await tx.get(paymentRef);
        const current = await tx.get(entitlementRef);
        if (!order.exists() || order.data().status !== 'link_ready' || used.exists()) throw Error('Đơn hoặc mã giao dịch không hợp lệ.');
        const oldUntil = current.data()?.validUntil?.toMillis?.() ?? 0;
        const until = Timestamp.fromMillis(Math.max(Date.now(), oldUntil) + 30 * DAY_MS);
        tx.set(paymentRef, { orderId: id, uid: data.uid, createdAt: serverTimestamp() });
        tx.update(orderRef, { status: 'paid', paidAt: serverTimestamp(), transactionRef: bankRef });
        tx.set(entitlementRef, { plan: 'pro', validUntil: until, sourceOrder: id, updatedAt: serverTimestamp() });
      });
      status(`Đã mở Pro sau đối soát cho đơn ${id}.`);
    } catch {
      status('Không duyệt được: đơn đã đổi trạng thái, mã giao dịch trùng hoặc thiếu quyền.');
      approve.disabled = false;
    }
  });
  actions.append(reference, approve);
  card.append(actions);
  return card;
}

function watchAdmin() {
  stopAdminOrders?.();
  stopAdminOrders = onSnapshot(collection(db, 'orders'), (snapshot) => {
    const list = $('admin-orders');
    list.replaceChildren();
    const orders = snapshot.docs.map((item) => ({ id: item.id, data: item.data() }));
    orders.sort((a, b) => (b.data.createdAt?.toMillis?.() ?? 0) - (a.data.createdAt?.toMillis?.() ?? 0));
    for (const { id, data } of orders) list.append(adminOrderCard(id, data));
    if (!orders.length) list.append(node('p', 'Chưa có yêu cầu Pro.'));
  }, () => status('Không đọc được hàng đợi Admin.'));
}

async function renderAccount(user) {
  stopMyOrders?.();
  stopAdminOrders?.();
  stopEntitlement?.();
  currentUser = user;
  show('signed-out', !user);
  show('register', false);
  show('dashboard', false);
  show('admin', false);
  if (!user) return status('Đăng nhập để bắt đầu.');
  try {
    const profile = await getDoc(doc(db, 'users', user.uid));
    if (currentUser?.uid !== user.uid) return;
    if (!profile.exists()) {
      $('register-email').textContent = user.email ?? '';
      show('register', true);
      return status('Hoàn tất đồng ý điều khoản để tạo tài khoản Free.');
    }
    $('account-name').textContent = user.displayName || 'Khách hàng LH25';
    $('account-email').textContent = user.email ?? '';
    show('dashboard', true);
    watchCustomer(user.uid);
    const admin = await getDoc(doc(db, 'admins', user.uid));
    if (currentUser?.uid !== user.uid) return;
    if (admin.exists()) {
      show('admin', true);
      watchAdmin();
    }
    status('Đã đăng nhập an toàn.');
  } catch {
    status('Chưa đọc được tài khoản. Dịch vụ có thể chưa được cấu hình; thử tải lại sau.');
  }
}

async function boot() {
  try {
    const response = await fetch('/__/firebase/init.json');
    if (!response.ok) throw Error('Firebase Hosting config unavailable');
    const config = await response.json();
    config.appId = FIREBASE_APP_ID;
    const app = initializeApp(config);
    auth = getAuth(app);
    db = getFirestore(app);
    $('google-login').addEventListener('click', async () => {
      try { await signInWithPopup(auth, new GoogleAuthProvider()); }
      catch (error) { status(error.code === 'auth/unauthorized-domain' ? 'Địa chỉ này chưa được cho phép đăng nhập Google.' : 'Đăng nhập Google chưa thành công. Vui lòng thử lại.'); }
    });
    $('logout').addEventListener('click', () => signOut(auth));
    $('accept-terms').addEventListener('change', () => { $('complete-register').disabled = !$('accept-terms').checked; });
    $('complete-register').addEventListener('click', async () => {
      if (!currentUser || !$('accept-terms').checked) return;
      $('complete-register').disabled = true;
      try {
        await setDoc(doc(db, 'users', currentUser.uid), {
          email: currentUser.email, displayName: (currentUser.displayName || '').slice(0, 120),
          acceptedTermsVersion: TERM_VERSION, createdAt: serverTimestamp(),
        });
        await renderAccount(currentUser);
      } catch {
        status('Chưa tạo được tài khoản Free. Vui lòng thử lại.');
        $('complete-register').disabled = false;
      }
    });
    $('request-pro').addEventListener('click', async () => {
      if (!currentUser || hasOpenOrder) return;
      $('request-pro').disabled = true;
      try {
        await addDoc(collection(db, 'orders'), {
          uid: currentUser.uid, email: currentUser.email,
          sku: 'pro-30d', amount: PRICE, status: 'requested', createdAt: serverTimestamp(),
        });
        status('Đã gửi yêu cầu. Chờ Admin tạo link payOS riêng; chưa chuyển khoản lúc này.');
      } catch {
        status('Chưa gửi được yêu cầu Pro. Vui lòng thử lại.');
        $('request-pro').disabled = false;
      }
    });
    onAuthStateChanged(auth, (user) => { void renderAccount(user); });
  } catch {
    status('Firebase chưa sẵn sàng. Trang này chưa nhận tài khoản hoặc thanh toán.');
  }
}

void boot();
