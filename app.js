/* =========================================================
   SCHOOLGUARD AI – app.js
   Luồng: Nguồn video → Phát hiện (AI) → Theo dõi (tracker)
          → Luật sự kiện → Cảnh báo → Xác minh → Nhật ký

   Mục lục:
    1. Hằng số & cấu hình mặc định
    2. Hình học
    3. Tracker (gán ID cho đối tượng qua các khung hình)
    4. Engine (vùng cấm, đếm người, đông người, vật bỏ quên)
    5. Sim (cảnh mô phỏng để chạy thử không cần camera)
    --- phần trên không phụ thuộc DOM nên kiểm thử được bằng Node ---
    6. Tiện ích & lưu trữ
    7. Nguồn video & bộ phát hiện AI
    8. Vẽ lên video (vùng, khung, HUD, làm mờ)
    9. Cảnh báo (danh sách, âm thanh, webhook, nhật ký)
   10. Công cụ vẽ vùng & giao diện
   11. Khởi động
   ========================================================= */
'use strict';

(() => {

  /* @pure-start */

  /* =======================================================
     1. HẰNG SỐ & CẤU HÌNH
     ======================================================= */
  const W = 960, H = 540;                                   // độ phân giải canvas; vùng lưu theo tỉ lệ 0–1
  const BAG_CLASSES = new Set(['backpack', 'handbag', 'suitcase']);
  const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6);

  const CAMERAS = [
    { id: 'cam1', name: 'Cổng trường' },
    { id: 'cam2', name: 'Hành lang tầng 1' },
    { id: 'cam3', name: 'Phòng thiết bị' },
    { id: 'cam4', name: 'Bãi xe' },
  ];

  const DEFAULTS = {
    schoolStart: '07:00', schoolEnd: '17:00', forceAfterHours: false,
    minScore: 50,          // % độ tin cậy tối thiểu của AI
    intrusionSec: 1,       // ở trong vùng cấm bao lâu thì báo
    loiterSec: 30,         // đứng lâu ở vùng theo dõi
    crowdCount: 8, crowdSec: 3,
    abandonedSec: 15,      // vật nằm yên, không có người gần
    cooldownSec: 30,       // giãn cách giữa hai cảnh báo cùng nguồn
    blurFaces: true, saveSnapshots: true, retentionDays: 7, sound: true, webhook: '',
  };

  const SETTING_FIELDS = [
    { key: 'schoolStart', label: 'Giờ học bắt đầu', type: 'time' },
    { key: 'schoolEnd', label: 'Giờ học kết thúc', type: 'time' },
    { key: 'forceAfterHours', label: 'Giả lập đang ngoài giờ học (để thử vùng cấm “chỉ ngoài giờ”)', type: 'checkbox' },
    { key: 'minScore', label: 'Độ tin cậy tối thiểu của AI (%)', type: 'number', min: 20, max: 95 },
    { key: 'intrusionSec', label: 'Ở trong vùng cấm tối thiểu (giây)', type: 'number', min: 0, max: 30 },
    { key: 'loiterSec', label: 'Đứng lâu ở vùng theo dõi (giây)', type: 'number', min: 5, max: 600 },
    { key: 'crowdCount', label: 'Ngưỡng đông người (số người)', type: 'number', min: 2, max: 100 },
    { key: 'crowdSec', label: 'Duy trì đông người tối thiểu (giây)', type: 'number', min: 1, max: 120 },
    { key: 'abandonedSec', label: 'Thời gian nghi bỏ quên (giây)', type: 'number', min: 5, max: 600 },
    { key: 'cooldownSec', label: 'Giãn cách giữa hai cảnh báo cùng nguồn (giây)', type: 'number', min: 5, max: 600 },
    { key: 'retentionDays', label: 'Tự xóa nhật ký sau (ngày)', type: 'number', min: 1, max: 365 },
    { key: 'saveSnapshots', label: 'Lưu ảnh chụp kèm cảnh báo (đã làm mờ nếu bật làm mờ)', type: 'checkbox' },
    { key: 'sound', label: 'Phát âm thanh khi có cảnh báo', type: 'checkbox' },
    { key: 'webhook', label: 'Webhook gửi cảnh báo (JSON, không kèm ảnh) tới backend/email', type: 'url' },
  ];

  const TYPE_LABEL = { intrusion: 'Xâm nhập', loiter: 'Đứng lâu', crowd: 'Đông người', abandoned: 'Vật bỏ quên' };
  const SEV_LABEL = { high: 'Khẩn', medium: 'Cần chú ý', low: 'Thông tin' };
  const STATUS_LABEL = { new: 'Mới', verifying: 'Đang xác minh', resolved: 'Đã xử lý', dismissed: 'Báo nhầm' };
  const OBJ_LABEL = { backpack: 'ba lô', handbag: 'túi xách', suitcase: 'vali' };

  /* Bố cục mặc định (khớp cảnh demo); người dùng vẽ lại cho camera thật */
  const defaultLayout = () => ({
    zones: [{
      id: uid(), name: 'Phòng thiết bị', type: 'forbidden', schedule: 'always',
      points: [[0.72, 0.42], [0.97, 0.42], [0.97, 0.68], [0.72, 0.68]],
    }],
    line: { a: [0.5, 0.62], b: [0.5, 0.98], flip: false },
  });


  /* =======================================================
     2. HÌNH HỌC
     ======================================================= */
  const pointInPolygon = (p, poly) => {
    let inside = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const [xi, yi] = poly[i], [xj, yj] = poly[j];
      if ((yi > p.y) !== (yj > p.y) && p.x < ((xj - xi) * (p.y - yi)) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  };

  const side = (a, b, p) => (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x);

  /* Đoạn p0→p1 có cắt đoạn a–b không? Trả 0 (không), +1 hoặc -1 (theo chiều cắt) */
  const crossing = (p0, p1, a, b) => {
    const s0 = side(a, b, p0), s1 = side(a, b, p1);
    if (s0 === 0 || s1 === 0 || (s0 > 0) === (s1 > 0)) return 0;
    const d0 = side(p0, p1, a), d1 = side(p0, p1, b);
    if ((d0 > 0) === (d1 > 0)) return 0;
    return s1 > 0 ? 1 : -1;
  };


  /* =======================================================
     3. TRACKER
     ======================================================= */
  class Tracker {
    constructor(maxMissed) { this.maxMissed = maxMissed; this.tracks = []; this.nextId = 1; }

    /* Ghép phát hiện mới với track cũ (gần nhất, cùng loại). Trả về các track đang thấy. */
    update(dets, now) {
      const pairs = [];
      this.tracks.forEach((tr, ti) => dets.forEach((d, di) => {
        if (tr.cls !== d.cls) return;
        const dist = Math.hypot(tr.cx - d.cx, tr.cy - d.cy);
        if (dist <= Math.max(tr.w, tr.h, 40) * 0.9) pairs.push({ ti, di, dist });
      }));
      pairs.sort((a, b) => a.dist - b.dist);

      const usedT = new Set(), usedD = new Set();
      for (const { ti, di } of pairs) {
        if (usedT.has(ti) || usedD.has(di)) continue;
        usedT.add(ti); usedD.add(di);
        this.apply(this.tracks[ti], dets[di], now);
      }
      dets.forEach((d, di) => { if (!usedD.has(di)) this.tracks.push(this.create(d, now)); });
      this.tracks = this.tracks.filter((tr) => now - tr.lastSeen <= this.maxMissed);
      return this.tracks.filter((tr) => tr.lastSeen === now);
    }

    create(d, now) {
      const tr = { id: this.nextId++, cls: d.cls, firstSeen: now, prevFoot: null, anchor: { x: d.cx, y: d.cy, t: now } };
      return this.apply(tr, d, now, true);
    }

    apply(tr, d, now, fresh = false) {
      if (!fresh) tr.prevFoot = tr.foot;
      Object.assign(tr, { x: d.x, y: d.y, w: d.w, h: d.h, cx: d.cx, cy: d.cy, score: d.score, lastSeen: now });
      tr.foot = { x: d.cx, y: d.y + d.h };
      // "đứng yên" = tâm chưa rời điểm neo quá ~20% kích thước
      if (Math.hypot(tr.cx - tr.anchor.x, tr.cy - tr.anchor.y) > Math.max(10, 0.2 * Math.max(tr.w, tr.h))) {
        tr.anchor = { x: tr.cx, y: tr.cy, t: now };
      }
      return tr;
    }
  }


  /* =======================================================
     4. ENGINE – các luật phát hiện sự kiện
     ======================================================= */
  const prep = (d) => ({ ...d, cx: d.x + d.w / 2, cy: d.y + d.h / 2 });

  class Engine {
    constructor(onEvent) { this.onEvent = onEvent; this.reset(); }

    reset() {
      this.people = new Tracker(1.5);
      this.objects = new Tracker(4);            // túi hay bị AI bỏ sót vài khung → giữ track lâu hơn
      this.dwell = new Map();                   // "idNgười:idVùng" → thời điểm vào vùng
      this.lastEmit = new Map();
      this.crowdSince = null;
      this.counts = { in: 0, out: 0 };
      this.view = { people: [], objects: [], flagged: new Set(), timers: new Map(), crowd: false };
    }

    emit(key, event, now, cooldown) {
      if (now - (this.lastEmit.get(key) ?? -Infinity) < cooldown) return;
      this.lastEmit.set(key, now);
      this.onEvent(event);
    }

    /* dets: [{cls, score, x, y, w, h}] theo toạ độ canvas */
    step(dets, now, { layout, settings, afterHours }) {
      const ok = dets.filter((d) => d.score >= settings.minScore / 100).map(prep);
      const people = this.people.update(ok.filter((d) => d.cls === 'person'), now);
      this.objects.update(ok.filter((d) => BAG_CLASSES.has(d.cls)), now);

      const flagged = new Set();                // 'p<id>' hoặc 'o<id>' đang bị cảnh báo
      const timers = new Map();                 // id vật → tiến độ 0–1 tới ngưỡng bỏ quên
      const zones = layout.zones
        .filter((z) => z.schedule === 'always' || afterHours)
        .map((z) => ({ ...z, px: z.points.map(([x, y]) => [x * W, y * H]) }));

      this.checkZones(people, zones, flagged, now, settings);
      this.checkCrowd(people, now, settings);
      this.checkLine(people, layout.line, now);
      this.checkAbandoned(people, flagged, timers, now, settings);

      this.view = { people, objects: this.objects.tracks, flagged, timers, crowd: people.length >= settings.crowdCount };
    }

    checkZones(people, zones, flagged, now, s) {
      const seen = new Set();
      for (const p of people) for (const z of zones) {
        if (!pointInPolygon(p.foot, z.px)) continue;
        const key = `${p.id}:${z.id}`;
        seen.add(key);
        if (!this.dwell.has(key)) this.dwell.set(key, now);
        const dwell = now - this.dwell.get(key);
        const forbidden = z.type === 'forbidden';
        if (dwell < (forbidden ? s.intrusionSec : s.loiterSec)) continue;

        flagged.add(`p${p.id}`);
        const after = z.schedule === 'always' ? '' : ' (ngoài giờ học)';
        this.emit(`zone:${z.id}`, forbidden
          ? { type: 'intrusion', severity: 'high', message: `Có người vào “${z.name}”${after}` }
          : { type: 'loiter', severity: 'medium', message: `Có người đứng lâu ${Math.round(dwell)} giây tại “${z.name}”` },
        now, s.cooldownSec);
      }
      for (const key of this.dwell.keys()) if (!seen.has(key)) this.dwell.delete(key);
    }

    checkCrowd(people, now, s) {
      const n = people.length;
      if (n < s.crowdCount) { this.crowdSince = null; return; }
      this.crowdSince ??= now;
      if (now - this.crowdSince < s.crowdSec) return;
      this.emit('crowd', {
        type: 'crowd', severity: n >= s.crowdCount * 1.5 ? 'high' : 'medium',
        message: `Mật độ cao: ${n} người trong khung hình`,
      }, now, s.cooldownSec);
    }

    /* Đếm lượt vào/ra khi điểm chân cắt vạch */
    checkLine(people, line, now) {
      if (!line?.a || !line?.b) return;
      const A = { x: line.a[0] * W, y: line.a[1] * H }, B = { x: line.b[0] * W, y: line.b[1] * H };
      for (const p of people) {
        if (!p.prevFoot || (p.lastCross && now - p.lastCross < 1)) continue;
        const c = crossing(p.prevFoot, p.foot, A, B);
        if (!c) continue;
        p.lastCross = now;
        (line.flip ? c < 0 : c > 0) ? this.counts.in++ : this.counts.out++;
      }
    }

    /* Vật bỏ quên = nằm yên + không có người ở gần liên tục đủ lâu.
       Người đi ngang qua (<3 giây gần vật) không bị tính là chủ. */
    checkAbandoned(people, flagged, timers, now, s) {
      for (const o of this.objects.tracks) {
        if (now - o.lastSeen > 2) continue;
        const near = people.some((p) => Math.hypot(p.cx - o.cx, p.cy - o.cy) < Math.max(p.h, 80) * 0.6);
        if (near) {
          o.nearSince ??= now;
          if (now - o.nearSince >= 3) o.awaySince = null;
        } else {
          o.nearSince = null;
          o.awaySince ??= now;
        }
        if (o.awaySince == null) continue;

        const waited = Math.min(now - o.awaySince, now - o.anchor.t);
        timers.set(o.id, Math.min(1, waited / s.abandonedSec));
        if (waited < s.abandonedSec) continue;
        flagged.add(`o${o.id}`);
        this.emit(`obj:${o.id}`, {
          type: 'abandoned', severity: 'high',
          message: `Nghi có ${OBJ_LABEL[o.cls]} bị bỏ quên, không có người gần hơn ${s.abandonedSec} giây`,
        }, now, Infinity);
      }
    }
  }


  /* =======================================================
     5. SIM – cảnh mô phỏng (người đi lại, kẻ xâm nhập, túi bỏ quên, tụ tập)
     ======================================================= */
  const Sim = {
    reset() {
      this.t = 0; this.id = 1; this.actors = []; this.bags = [];
      this.timers = { walker: 0.3, carrier: 5, intruder: 12, crowd: 60 };
    },
    hAt: (y) => 60 + (y - 300) * 0.55,                      // chiều cao người theo độ sâu (gần camera → to hơn)
    rand: (a, b) => a + Math.random() * (b - a),

    spawn(kind) {
      const dir = Math.random() < 0.5 ? 1 : -1;
      const a = {
        id: this.id++, kind, dir, x: dir > 0 ? -40 : W + 40, y: this.rand(390, 500),
        speed: this.rand(70, 120), state: 'walk', timer: 0, hue: Math.floor(this.rand(0, 360)),
      };
      if (kind === 'intruder') Object.assign(a, { dir: 1, x: -40, y: 420, speed: 100 });
      if (kind === 'carrier') a.dropX = this.rand(300, 560);
      this.actors.push(a);
    },

    spawnCrowd() {
      const cx = this.rand(360, 560);
      for (let i = 0; i < 9; i++) {
        const dir = i % 2 ? 1 : -1;
        this.actors.push({
          id: this.id++, kind: 'crowd', dir, speed: 120, state: 'goto', timer: 0, hue: Math.floor(this.rand(0, 360)),
          x: dir > 0 ? -40 - i * 30 : W + 40 + i * 30, y: this.rand(400, 500),
          target: { x: cx + this.rand(-130, 130), y: this.rand(400, 500) },
        });
      }
    },

    update(dt) {
      this.t += dt;
      const plan = {
        walker: [() => this.spawn('walker'), 3, 6],
        carrier: [() => this.spawn('carrier'), 50, 70],
        intruder: [() => this.spawn('intruder'), 40, 60],
        crowd: [() => this.spawnCrowd(), 100, 140],
      };
      for (const k in plan) {
        this.timers[k] -= dt;
        if (this.timers[k] <= 0) { plan[k][0](); this.timers[k] = this.rand(plan[k][1], plan[k][2]); }
      }
      this.actors.forEach((a) => this.move(a, dt));
      this.actors = this.actors.filter((a) => !(a.seen && (a.x < -80 || a.x > W + 80)));
      this.bags.forEach((b) => { b.ttl -= dt; });
      this.bags = this.bags.filter((b) => b.ttl > 0);
    },

    move(a, dt) {
      if (a.x > 0 && a.x < W) a.seen = true;
      switch (a.state) {
        case 'walk':
          a.x += a.dir * a.speed * dt;
          if (a.kind === 'intruder' && !a.entered && a.x >= 790) { a.entered = true; a.state = 'enter'; }
          if (a.kind === 'carrier' && !a.dropped && (a.x - a.dropX) * a.dir >= 0) { a.state = 'drop'; a.timer = 1.2; }
          break;
        case 'enter': a.y -= 55 * dt; if (a.y <= 320) { a.state = 'linger'; a.timer = 5; } break;
        case 'linger': a.timer -= dt; if (a.timer <= 0) a.state = 'exit'; break;
        case 'exit': a.y += 55 * dt; if (a.y >= 430) a.state = 'walk'; break;
        case 'drop':
          a.timer -= dt;
          if (a.timer <= 0) { this.bags.push({ x: a.x + a.dir * 26, y: a.y, ttl: 70 }); a.dropped = true; a.state = 'walk'; }
          break;
        case 'goto': {
          const dx = a.target.x - a.x, dy = a.target.y - a.y, d = Math.hypot(dx, dy);
          if (d < 4) { a.state = 'idle'; a.timer = this.rand(9, 12); }
          else { a.x += (dx / d) * a.speed * dt; a.y += (dy / d) * a.speed * dt; }
          break;
        }
        case 'idle': a.timer -= dt; if (a.timer <= 0) { a.state = 'leave'; a.dir = Math.random() < 0.5 ? 1 : -1; } break;
        case 'leave': a.x += a.dir * a.speed * dt; break;
      }
    },

    /* "Kết quả AI" của cảnh mô phỏng: khung bao quanh người và túi */
    detections() {
      const dets = this.actors.filter((a) => a.x > 0 && a.x < W).map((a) => {
        const h = this.hAt(a.y), w = h * 0.36;
        return { cls: 'person', score: 0.9, x: a.x - w / 2, y: a.y - h, w, h };
      });
      this.bags.forEach((b) => {
        const w = this.hAt(b.y) * 0.34, h = this.hAt(b.y) * 0.28;
        dets.push({ cls: 'backpack', score: 0.85, x: b.x - w / 2, y: b.y - h, w, h });
      });
      return dets;
    },

    draw(ctx) {
      ctx.fillStyle = '#c3ccd7'; ctx.fillRect(0, 0, W, 260);                       // tường
      ctx.fillStyle = '#aab6c4';
      for (let x = 60; x < W; x += 170) ctx.fillRect(x, 70, 90, 110);              // cửa sổ
      ctx.fillStyle = '#5a4535'; ctx.fillRect(740, 110, 100, 150);                 // cửa phòng thiết bị
      ctx.fillStyle = '#e9edf2'; ctx.font = '600 13px Barlow, sans-serif'; ctx.fillText('Phòng thiết bị', 750, 100);
      const floor = ctx.createLinearGradient(0, 260, 0, H);
      floor.addColorStop(0, '#8d99a8'); floor.addColorStop(1, '#6a7686');
      ctx.fillStyle = floor; ctx.fillRect(0, 260, W, H - 260);
      ctx.strokeStyle = 'rgba(255,255,255,.12)'; ctx.lineWidth = 1;
      for (let i = 0; i < 9; i++) {                                                // vạch gạch sàn theo phối cảnh
        const y = 262 + i * i * 3.8 + i * 6;
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
      }

      const items = [...this.bags.map((b) => ({ y: b.y, bag: b })), ...this.actors.map((a) => ({ y: a.y, actor: a }))]
        .sort((p, q) => p.y - q.y);
      items.forEach((it) => (it.bag ? this.drawBag(ctx, it.bag) : this.drawActor(ctx, it.actor)));
    },

    drawBag(ctx, b) {
      const w = this.hAt(b.y) * 0.34, h = this.hAt(b.y) * 0.28;
      ctx.fillStyle = 'rgba(0,0,0,.25)'; ctx.fillRect(b.x - w / 2, b.y - 3, w, 4);
      ctx.fillStyle = '#2f5d8a'; ctx.fillRect(b.x - w / 2, b.y - h, w, h);
      ctx.fillStyle = '#244a6f'; ctx.fillRect(b.x - w / 2, b.y - h, w, h * 0.3);
    },

    drawActor(ctx, a) {
      const h = this.hAt(a.y), w = h * 0.36, swing = Math.sin(this.t * 8 + a.id) * w * 0.12;
      ctx.fillStyle = 'rgba(0,0,0,.25)';
      ctx.beginPath(); ctx.ellipse(a.x, a.y, w * 0.6, h * 0.04, 0, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = '#2b3345';                                                   // chân
      ctx.fillRect(a.x - w * 0.28 + swing, a.y - h * 0.38, w * 0.24, h * 0.38);
      ctx.fillRect(a.x + w * 0.04 - swing, a.y - h * 0.38, w * 0.24, h * 0.38);
      ctx.fillStyle = `hsl(${a.hue} 45% 48%)`;                                     // thân
      ctx.fillRect(a.x - w * 0.4, a.y - h * 0.82, w * 0.8, h * 0.46);
      ctx.fillStyle = '#d9b595';                                                   // đầu
      ctx.beginPath(); ctx.arc(a.x, a.y - h * 0.9, h * 0.095, 0, Math.PI * 2); ctx.fill();
    },
  };

  /* @pure-end */


  /* =======================================================
     6. TIỆN ÍCH & LƯU TRỮ
     ======================================================= */
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  const KEY = { settings: 'schoolguard.settings', layout: 'schoolguard.layout', alerts: 'schoolguard.alerts', cam: 'schoolguard.cam' };
  const MAX_ALERTS = 100;

  const Store = {
    get(key, fallback) { try { const raw = localStorage.getItem(key); return raw ? JSON.parse(raw) : fallback; } catch { return fallback; } },
    set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch { return false; } },
  };

  let settings = { ...DEFAULTS, ...Store.get(KEY.settings, {}) };
  let layouts = Store.get(KEY.layout, {});
  let alerts = Store.get(KEY.alerts, []);
  let camId = CAMERAS.some((c) => c.id === Store.get(KEY.cam)) ? Store.get(KEY.cam) : CAMERAS[0].id;

  const cam = () => CAMERAS.find((c) => c.id === camId);
  const layout = () => (layouts[camId] ??= defaultLayout());
  const saveLayout = () => Store.set(KEY.layout, layouts);
  const saveSettings = () => Store.set(KEY.settings, settings);
  const isOpen = (a) => a.status === 'new' || a.status === 'verifying';

  function toast(message, type = '') {
    const el = Object.assign(document.createElement('div'), { className: `toast ${type}`, textContent: message });
    $('#toasts').append(el);
    setTimeout(() => el.remove(), 5000);
  }

  function isAfterHours() {
    if (settings.forceAfterHours) return true;
    const d = new Date(), mins = d.getHours() * 60 + d.getMinutes();
    const toMin = (hhmm) => { const [h, m] = hhmm.split(':').map(Number); return h * 60 + m; };
    return mins < toMin(settings.schoolStart) || mins >= toMin(settings.schoolEnd);
  }

  const engine = new Engine((event) => onEvent(event));
  const stepContext = () => ({ layout: layout(), settings, afterHours: isAfterHours() });


  /* =======================================================
     7. NGUỒN VIDEO & BỘ PHÁT HIỆN AI
     ======================================================= */
  const canvas = $('#view');
  const ctx = canvas.getContext('2d');
  const video = $('#video');
  const src = { kind: 'demo', stream: null, url: null, token: null };
  let fps = 0;

  const TFJS_URL = 'https://cdn.jsdelivr.net/npm/@tensorflow/tfjs@4.22.0/dist/tf.min.js';
  const COCO_URL = 'https://cdn.jsdelivr.net/npm/@tensorflow-models/coco-ssd@2.2.3/dist/coco-ssd.min.js';

  const loadScript = (url) => new Promise((resolve, reject) => {
    const s = Object.assign(document.createElement('script'), { src: url, onload: resolve, onerror: () => reject(new Error(url)) });
    document.head.append(s);
  });

  /* COCO-SSD chạy ngay trên trình duyệt (TensorFlow.js), tải mô hình một lần */
  const Detector = {
    model: null, loading: null,
    load() {
      this.loading ??= (async () => {
        await loadScript(TFJS_URL);
        await loadScript(COCO_URL);
        this.model = await window.cocoSsd.load({ base: 'lite_mobilenet_v2' });
      })().catch((err) => { this.loading = null; throw err; });
      return this.loading;
    },
    async detect() {
      const preds = await this.model.detect(video, 30, 0.3);
      const v = viewTransform();
      return preds
        .filter((p) => p.class === 'person' || BAG_CLASSES.has(p.class))
        .map((p) => ({
          cls: p.class, score: p.score,
          x: p.bbox[0] * v.s + v.ox, y: p.bbox[1] * v.s + v.oy, w: p.bbox[2] * v.s, h: p.bbox[3] * v.s,
        }));
    },
  };

  function viewTransform() {
    const vw = video.videoWidth || W, vh = video.videoHeight || H, s = Math.min(W / vw, H / vh);
    return { s, vw, vh, ox: (W - vw * s) / 2, oy: (H - vh * s) / 2 };
  }

  function setModelChip(state, text) {
    const chip = $('#modelChip');
    chip.className = `chip ${state}`;
    chip.textContent = text;
  }

  function stopSource() {
    src.token = null;
    src.stream?.getTracks().forEach((t) => t.stop());
    if (src.url) URL.revokeObjectURL(src.url);
    Object.assign(src, { stream: null, url: null });
    video.pause();
    video.removeAttribute('src');
    video.srcObject = null;
  }

  async function setSource(kind, file) {
    stopSource();
    engine.reset();
    fps = 0;
    $('#demoActions').hidden = kind !== 'demo';

    if (kind === 'demo') {
      Sim.reset();
      src.kind = 'demo';
      $('#source').value = 'demo';
      setModelChip('', 'Chế độ demo mô phỏng');
      return;
    }

    const token = (src.token = Symbol());
    try {
      setModelChip('loading', 'Đang tải mô hình AI…');
      const loading = Detector.load();
      loading.catch(() => {});                                      // lỗi sẽ được bắt ở `await loading` bên dưới
      if (kind === 'webcam') {
        src.stream = await navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720 }, audio: false });
        video.srcObject = src.stream;
      } else {
        src.url = URL.createObjectURL(file);
        video.src = src.url;
        video.loop = true;
      }
      await video.play();
      await loading;
      if (src.token !== token) return;
      src.kind = kind;
      setModelChip('ready', 'AI COCO-SSD chạy trên máy');
      inferLoop(token);
    } catch (err) {
      console.error(err);
      const offline = String(err.message).startsWith('http');
      toast(offline ? 'Không tải được mô hình AI (cần Internet ở lần đầu). Quay về chế độ demo.'
        : 'Không mở được nguồn video (webcam cần HTTPS hoặc localhost và quyền truy cập). Quay về chế độ demo.', 'error');
      setSource('demo');
    }
  }

  async function inferLoop(token) {
    while (src.token === token) {
      if (video.readyState < 2) { await sleep(100); continue; }
      const t0 = performance.now();
      try {
        engine.step(await Detector.detect(), t0 / 1000, stepContext());
        fps = fps * 0.8 + (1000 / (performance.now() - t0)) * 0.2;
      } catch (err) { console.error(err); await sleep(500); }
      await sleep(0);
    }
  }


  /* =======================================================
     8. VẼ LÊN VIDEO
     ======================================================= */
  const COLORS = { person: '#3b82f6', alert: '#ef4444', object: '#f59e0b' };
  const tool = { name: null, draft: [], hover: null };
  const banner = { text: '', severity: 'high', until: 0 };
  const hatch = {};
  const px = Object.assign(document.createElement('canvas'), {});     // bộ đệm cho làm mờ
  const pxCtx = px.getContext('2d');

  function hatchPattern(color) {
    if (!hatch[color]) {
      const c = Object.assign(document.createElement('canvas'), { width: 18, height: 18 });
      const g = c.getContext('2d');
      g.strokeStyle = color; g.lineWidth = 5;
      [[0, 18, 18, 0], [-9, 9, 9, -9], [9, 27, 27, 9]].forEach(([x1, y1, x2, y2]) => { g.beginPath(); g.moveTo(x1, y1); g.lineTo(x2, y2); g.stroke(); });
      hatch[color] = ctx.createPattern(c, 'repeat');
    }
    return hatch[color];
  }

  function drawVideo() {
    ctx.fillStyle = '#0e141b'; ctx.fillRect(0, 0, W, H);
    if (video.readyState < 2) return;
    const v = viewTransform();
    ctx.drawImage(video, v.ox, v.oy, v.vw * v.s, v.vh * v.s);
  }

  /* Làm mờ (pixelate) vùng đầu của mỗi người trước khi vẽ bất kỳ thứ gì khác */
  function blurHeads(people) {
    ctx.imageSmoothingEnabled = false;
    for (const p of people) {
      const x = Math.max(0, p.x + p.w * 0.1), y = Math.max(0, p.y - p.h * 0.02);
      const w = Math.min(W - x, p.w * 0.8), h = Math.min(H - y, p.h * 0.3);
      if (w < 4 || h < 4) continue;
      const cell = Math.max(4, Math.round(Math.min(w, h) / 4));
      px.width = Math.max(1, Math.round(w / cell)); px.height = Math.max(1, Math.round(h / cell));
      pxCtx.drawImage(canvas, x, y, w, h, 0, 0, px.width, px.height);
      ctx.drawImage(px, 0, 0, px.width, px.height, x, y, w, h);
    }
    ctx.imageSmoothingEnabled = true;
  }

  function tag(text, x, y, bg) {
    ctx.font = '600 13px Barlow, sans-serif';
    const w = ctx.measureText(text).width + 10, ty = Math.max(18, y);
    ctx.fillStyle = bg; ctx.fillRect(x, ty - 18, w, 18);
    ctx.fillStyle = '#fff'; ctx.fillText(text, x + 5, ty - 5);
  }

  function drawZones() {
    const after = isAfterHours();
    for (const z of layout().zones) {
      const active = z.schedule === 'always' || after;
      const color = z.type === 'forbidden' ? '#f2b705' : '#3b82f6';
      ctx.beginPath();
      z.points.forEach(([x, y], i) => (i ? ctx.lineTo(x * W, y * H) : ctx.moveTo(x * W, y * H)));
      ctx.closePath();
      ctx.fillStyle = active ? hatchPattern(color === '#f2b705' ? 'rgba(242,183,5,.55)' : 'rgba(59,130,246,.5)') : 'rgba(255,255,255,.06)';
      ctx.fill();
      ctx.lineWidth = 3; ctx.strokeStyle = active ? color : 'rgba(255,255,255,.5)';
      ctx.setLineDash(active ? [] : [8, 6]); ctx.stroke(); ctx.setLineDash([]);
      const label = `${z.type === 'forbidden' ? 'Vùng cấm' : 'Theo dõi'}: ${z.name}${active ? '' : ' (chưa hiệu lực)'}`;
      tag(label, z.points[0][0] * W, z.points[0][1] * H, active ? (z.type === 'forbidden' ? '#7a5c00' : '#1d4ed8') : '#55606e');
    }
  }

  function drawLine() {
    const l = layout().line;
    if (!l?.a || !l?.b) return;
    const [ax, ay, bx, by] = [l.a[0] * W, l.a[1] * H, l.b[0] * W, l.b[1] * H];
    ctx.strokeStyle = '#22d3ee'; ctx.lineWidth = 3; ctx.setLineDash([10, 6]);
    ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke(); ctx.setLineDash([]);
    tag(`Vào ${engine.counts.in} · Ra ${engine.counts.out}`, (ax + bx) / 2 + 8, (ay + by) / 2, '#0e7490');
  }

  function drawBoxes() {
    const { people, objects, flagged, timers } = engine.view;
    ctx.lineWidth = 2;
    for (const p of people) {
      const bad = flagged.has(`p${p.id}`);
      ctx.strokeStyle = bad ? COLORS.alert : COLORS.person;
      ctx.lineWidth = bad ? 3 : 2;
      ctx.strokeRect(p.x, p.y, p.w, p.h);
      tag(`Người #${p.id}${bad ? ' – cảnh báo' : ''}`, p.x, p.y, bad ? COLORS.alert : COLORS.person);
    }
    for (const o of objects) {
      if (performance.now() / 1000 - o.lastSeen > 0.5) continue;           // bỏ qua track đã mất dấu
      const bad = flagged.has(`o${o.id}`), ratio = timers.get(o.id) ?? 0;
      ctx.strokeStyle = bad ? COLORS.alert : COLORS.object;
      ctx.lineWidth = bad ? 3 : 2;
      ctx.strokeRect(o.x, o.y, o.w, o.h);
      const name = OBJ_LABEL[o.cls];
      tag(bad ? `Bỏ quên: ${name}` : ratio > 0 ? `${name}, chờ ${Math.round(ratio * settings.abandonedSec)}/${settings.abandonedSec}s` : name,
        o.x, o.y, bad ? COLORS.alert : '#9a6200');
    }
  }

  function drawHud(now) {
    ctx.fillStyle = 'rgba(14,20,27,.7)'; ctx.fillRect(10, 10, 230, 28);
    ctx.fillStyle = '#ff4d3d'; ctx.beginPath(); ctx.arc(24, 24, 5, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = '#fff'; ctx.font = '600 14px Barlow, sans-serif';
    ctx.fillText(`${cam().name}: ${src.kind === 'demo' ? 'mô phỏng' : 'trực tiếp'}`, 36, 29);
    if (banner.until > now) {
      ctx.fillStyle = banner.severity === 'high' ? 'rgba(217,45,32,.92)' : 'rgba(194,106,0,.92)';
      ctx.fillRect(W / 2 - 300, 10, 600, 34);
      ctx.fillStyle = '#fff'; ctx.font = '700 17px Barlow, sans-serif'; ctx.textAlign = 'center';
      ctx.fillText(banner.text, W / 2, 33); ctx.textAlign = 'left';
    }
  }

  function drawDraft() {
    if (!tool.name || !tool.draft.length) return;
    const pts = [...tool.draft, ...(tool.hover ? [tool.hover] : [])];
    ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.setLineDash([6, 4]);
    ctx.beginPath(); pts.forEach(([x, y], i) => (i ? ctx.lineTo(x * W, y * H) : ctx.moveTo(x * W, y * H))); ctx.stroke();
    ctx.setLineDash([]);
    tool.draft.forEach(([x, y], i) => { ctx.fillStyle = i ? '#fff' : '#f2b705'; ctx.beginPath(); ctx.arc(x * W, y * H, i ? 4 : 7, 0, Math.PI * 2); ctx.fill(); });
  }

  let lastT = performance.now() / 1000;
  function frame() {
    requestAnimationFrame(frame);
    const now = performance.now() / 1000;
    Sim.dt = Math.min(0.1, now - lastT); lastT = now;

    if (src.kind === 'demo') {
      Sim.update(Sim.dt);
      engine.step(Sim.detections(), now, stepContext());
      Sim.draw(ctx);
    } else drawVideo();

    if (settings.blurFaces) blurHeads(engine.view.people);
    drawZones(); drawLine(); drawBoxes(); drawDraft(); drawHud(now);
  }


  /* =======================================================
     9. CẢNH BÁO
     ======================================================= */
  let alertFilter = 'open';
  let audio = null;
  const snapCanvas = Object.assign(document.createElement('canvas'), { width: 320, height: 180 });

  function snapshot() {
    snapCanvas.getContext('2d').drawImage(canvas, 0, 0, 320, 180);
    return snapCanvas.toDataURL('image/jpeg', 0.6);
  }

  function beep(severity) {
    if (!settings.sound) return;
    try {
      audio ??= new AudioContext();
      [0, 0.22].slice(0, severity === 'high' ? 2 : 1).forEach((delay) => {
        const osc = audio.createOscillator(), gain = audio.createGain();
        osc.frequency.value = severity === 'high' ? 920 : 640;
        gain.gain.setValueAtTime(0.15, audio.currentTime + delay);
        gain.gain.exponentialRampToValueAtTime(0.001, audio.currentTime + delay + 0.18);
        osc.connect(gain).connect(audio.destination);
        osc.start(audio.currentTime + delay); osc.stop(audio.currentTime + delay + 0.2);
      });
    } catch { /* trình duyệt chặn âm thanh đến khi người dùng tương tác */ }
  }

  function persistAlerts() {
    if (Store.set(KEY.alerts, alerts)) return;
    alerts.slice(25).forEach((a) => { a.snapshot = null; });          // hết dung lượng → bỏ ảnh của bản ghi cũ
    Store.set(KEY.alerts, alerts);
  }

  function onEvent(event) {
    const alert = {
      id: uid(), ts: Date.now(), cam: camId, camName: cam().name, status: 'new',
      snapshot: settings.saveSnapshots ? snapshot() : null, ...event,
    };
    alerts.unshift(alert);
    alerts.length = Math.min(alerts.length, MAX_ALERTS);
    persistAlerts();

    Object.assign(banner, { text: `${TYPE_LABEL[alert.type]}: ${alert.message}`.slice(0, 62), severity: alert.severity, until: performance.now() / 1000 + 4 });
    const stage = $('#stage');
    stage.classList.add('alarm');
    clearTimeout(onEvent.timer);
    onEvent.timer = setTimeout(() => stage.classList.remove('alarm'), 4000);

    beep(alert.severity);
    sendWebhook(alert);
    renderAlerts();
  }

  /* Kênh thông báo ngoài: gửi JSON (không có ảnh) tới backend để chuyển email/ứng dụng nội bộ */
  function sendWebhook(alert) {
    if (!settings.webhook) return;
    const { snapshot: _omit, ...payload } = alert;
    fetch(settings.webhook, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), keepalive: true })
      .catch(() => {});
  }

  function purgeOld() {
    const cutoff = Date.now() - settings.retentionDays * 864e5;
    const kept = alerts.filter((a) => a.ts >= cutoff);
    if (kept.length !== alerts.length) { alerts = kept; persistAlerts(); }
  }

  const fmtTime = (ms) => new Date(ms).toLocaleString('vi-VN', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });

  function alertCard(a) {
    const actions = a.status === 'new'
      ? `<button type="button" class="btn sm primary" data-act="verifying">Xác minh</button>
         <button type="button" class="btn sm" data-act="dismissed">Báo nhầm</button>`
      : a.status === 'verifying'
        ? `<button type="button" class="btn sm primary" data-act="resolved">Đã xử lý</button>
           <button type="button" class="btn sm" data-act="dismissed">Báo nhầm</button>`
        : '';
    return `
      <article class="alert ${a.severity} ${isOpen(a) ? '' : 'closed'}" data-id="${esc(a.id)}">
        ${a.snapshot ? `<img class="alert-thumb" src="${esc(a.snapshot)}" alt="Ảnh chụp lúc cảnh báo">` : '<div class="alert-thumb none">Không lưu ảnh</div>'}
        <div class="alert-body">
          <div class="alert-top"><span class="sev">${SEV_LABEL[a.severity]}</span><b>${TYPE_LABEL[a.type] ?? esc(a.type)}</b>
            <span class="state ${a.status}">${STATUS_LABEL[a.status]}</span></div>
          <p class="alert-msg">${esc(a.message)}</p>
          <p class="alert-meta">${esc(a.camName)}, ${fmtTime(a.ts)}</p>
        </div>
        ${actions ? `<div class="alert-actions">${actions}</div>` : ''}
      </article>`;
  }

  function renderAlerts() {
    const open = alerts.filter(isOpen);
    const list = alertFilter === 'open' ? open : alerts;
    $('#alertList').innerHTML = list.length
      ? list.map(alertCard).join('')
      : `<p class="empty">${alertFilter === 'open' ? 'Không có cảnh báo đang mở. Hệ thống vẫn đang theo dõi.' : 'Nhật ký trống.'}</p>`;
    $$('#alertTabs button').forEach((b) => b.classList.toggle('active', b.dataset.f === alertFilter));

    const badge = $('#openBadge');
    badge.hidden = !open.length;
    badge.textContent = open.length;
    document.title = `${open.length ? `(${open.length}) ` : ''}SchoolGuard AI`;
    renderCamTabs();
  }

  function exportCsv() {
    const q = (v) => `"${String(v).replace(/"/g, '""')}"`;
    const rows = [['Thời gian', 'Camera', 'Loại', 'Mức độ', 'Nội dung', 'Trạng thái'],
      ...alerts.map((a) => [new Date(a.ts).toISOString(), a.camName, TYPE_LABEL[a.type], SEV_LABEL[a.severity], a.message, STATUS_LABEL[a.status]])];
    const blob = new Blob(['\ufeff' + rows.map((r) => r.map(q).join(',')).join('\n')], { type: 'text/csv;charset=utf-8' });
    const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: `schoolguard-nhat-ky-${Date.now()}.csv` });
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function bindAlerts() {
    $('#alertTabs').addEventListener('click', (e) => { if (e.target.dataset.f) { alertFilter = e.target.dataset.f; renderAlerts(); } });
    $('#alertList').addEventListener('click', (e) => {
      const btn = e.target.closest('[data-act]');
      const a = btn && alerts.find((x) => x.id === btn.closest('.alert').dataset.id);
      if (!a) return;
      a.status = btn.dataset.act;
      a.handledAt = Date.now();
      persistAlerts();
      renderAlerts();
    });
    $('#btnExport').addEventListener('click', exportCsv);
    $('#btnClearLog').addEventListener('click', () => {
      if (!confirm('Xóa toàn bộ nhật ký cảnh báo? Không thể hoàn tác.')) return;
      alerts = [];
      persistAlerts();
      renderAlerts();
    });
  }


  /* =======================================================
     10. CÔNG CỤ VẼ VÙNG & GIAO DIỆN
     ======================================================= */
  const TOOL_HINT = {
    none: 'Chọn một công cụ để vẽ vùng cấm, vùng theo dõi hoặc vạch đếm trực tiếp trên video.',
    forbidden: 'Bấm từng góc của vùng cấm. Bấm gần điểm đầu (chấm vàng) hoặc nhấn Enter để khép vùng, Esc để hủy.',
    watch: 'Bấm từng góc của vùng theo dõi (đứng lâu sẽ báo). Bấm gần điểm đầu hoặc nhấn Enter để khép vùng, Esc để hủy.',
    line: 'Bấm hai điểm để đặt vạch đếm người vào/ra.',
  };

  function setTool(name) {
    tool.name = tool.name === name ? null : name;
    tool.draft = []; tool.hover = null;
    $$('.tool').forEach((b) => b.classList.toggle('active', b.dataset.tool === tool.name));
    $('#stage').classList.toggle('drawing', !!tool.name);
    $('#toolHint').textContent = TOOL_HINT[tool.name ?? 'none'];
  }

  function finishPolygon() {
    if (tool.draft.length < 3) return;
    const zones = layout().zones, forbidden = tool.name === 'forbidden';
    zones.push({
      id: uid(), type: tool.name, schedule: 'always', points: tool.draft,
      name: `${forbidden ? 'Vùng cấm' : 'Vùng theo dõi'} ${zones.filter((z) => z.type === tool.name).length + 1}`,
    });
    saveLayout(); setTool(tool.name); renderZones();
  }

  const canvasPoint = (e) => {
    const r = canvas.getBoundingClientRect();
    return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))];
  };

  function bindCanvas() {
    canvas.addEventListener('mousemove', (e) => { if (tool.name) tool.hover = canvasPoint(e); });
    canvas.addEventListener('mouseleave', () => { tool.hover = null; });
    canvas.addEventListener('click', (e) => {
      if (!tool.name) return;
      const p = canvasPoint(e);
      if (tool.name === 'line') {
        tool.draft.push(p);
        if (tool.draft.length === 2) {
          Object.assign(layout().line ??= {}, { a: tool.draft[0], b: tool.draft[1] });
          saveLayout(); setTool('line'); engine.counts = { in: 0, out: 0 };
        }
        return;
      }
      const first = tool.draft[0];
      if (first && tool.draft.length >= 3 && Math.hypot((p[0] - first[0]) * W, (p[1] - first[1]) * H) < 16) finishPolygon();
      else tool.draft.push(p);
    });
    document.addEventListener('keydown', (e) => {
      if (!tool.name) return;
      if (e.key === 'Escape') setTool(tool.name);
      if (e.key === 'Enter' && tool.name !== 'line') finishPolygon();
    });
  }

  function renderZones() {
    const zones = layout().zones;
    $('#zoneList').innerHTML = zones.length ? zones.map((z) => `
      <li class="zone-item" data-id="${esc(z.id)}">
        <span class="swatch ${esc(z.type)}" title="${z.type === 'forbidden' ? 'Vùng cấm' : 'Vùng theo dõi'}"></span>
        <input class="zone-name" value="${esc(z.name)}" maxlength="40" aria-label="Tên vùng">
        <select class="zone-schedule" aria-label="Thời gian hiệu lực">
          <option value="always" ${z.schedule === 'always' ? 'selected' : ''}>Luôn hiệu lực</option>
          <option value="afterhours" ${z.schedule === 'afterhours' ? 'selected' : ''}>Chỉ ngoài giờ học</option>
        </select>
        <button type="button" class="btn sm danger" data-del>Xóa</button>
      </li>`).join('') : '<li class="empty">Chưa có vùng nào. Chọn “Vẽ vùng cấm” rồi bấm lên video.</li>';
  }

  function bindZones() {
    const list = $('#zoneList');
    const zoneOf = (el) => layout().zones.find((z) => z.id === el.closest('.zone-item')?.dataset.id);
    list.addEventListener('input', (e) => { const z = zoneOf(e.target); if (z && e.target.classList.contains('zone-name')) { z.name = e.target.value; saveLayout(); } });
    list.addEventListener('change', (e) => { const z = zoneOf(e.target); if (z && e.target.classList.contains('zone-schedule')) { z.schedule = e.target.value; saveLayout(); } });
    list.addEventListener('click', (e) => {
      if (!e.target.matches('[data-del]')) return;
      const z = zoneOf(e.target);
      layout().zones = layout().zones.filter((x) => x !== z);
      saveLayout(); renderZones();
    });

    $('#btnClear').addEventListener('click', () => {
      if (!confirm('Xóa tất cả vùng và vạch đếm của camera này?')) return;
      layouts[camId] = { zones: [], line: null };
      saveLayout(); renderZones();
    });
    $('#btnFlip').addEventListener('click', () => {
      const l = layout().line;
      if (!l) return toast('Chưa có vạch đếm. Hãy chọn “Đặt vạch đếm” trước.');
      l.flip = !l.flip; saveLayout();
    });
  }

  function renderCamTabs() {
    $('#camTabs').innerHTML = CAMERAS.map((c) => {
      const n = alerts.filter((a) => a.cam === c.id && isOpen(a)).length;
      return `<button type="button" class="cam-tab ${c.id === camId ? 'active' : ''}" data-id="${c.id}">
        <span class="live-dot ${c.id === camId ? 'on' : ''}"></span>${esc(c.name)}${n ? `<span class="badge">${n}</span>` : ''}</button>`;
    }).join('');
  }

  /* --- Cài đặt --- */
  function openSettings() {
    $('#settingsFields').innerHTML = SETTING_FIELDS.map((f) => (f.type === 'checkbox'
      ? `<label class="check"><input type="checkbox" name="${f.key}" ${settings[f.key] ? 'checked' : ''}><span>${f.label}</span></label>`
      : `<label class="field"><span>${f.label}</span>
           <input name="${f.key}" type="${f.type}" value="${esc(settings[f.key])}" ${f.min != null ? `min="${f.min}" max="${f.max}"` : ''}></label>`)).join('');
    $('#dlgSettings').showModal();
  }

  function applySettings(next) {
    settings = { ...settings, ...next };
    saveSettings();
    purgeOld();
    syncPrivacy();
    renderAlerts();
  }

  function syncPrivacy() {
    $('#blurToggle').checked = settings.blurFaces;
    $('#retentionText').textContent = settings.retentionDays;
  }

  function bindSettings() {
    $('#btnSettings').addEventListener('click', openSettings);
    $('#formSettings').addEventListener('submit', (e) => {
      e.preventDefault();
      const next = {};
      SETTING_FIELDS.forEach((f) => {
        const el = e.target.elements[f.key];
        next[f.key] = f.type === 'checkbox' ? el.checked
          : f.type === 'number' ? Math.min(f.max, Math.max(f.min, Number(el.value) || DEFAULTS[f.key]))
          : el.value.trim();
      });
      applySettings(next);
      $('#dlgSettings').close();
      toast('Đã lưu cài đặt');
    });
    $('#btnDefaults').addEventListener('click', () => { applySettings({ ...DEFAULTS }); openSettings(); });

    $('#blurToggle').addEventListener('change', (e) => {
      if (!e.target.checked && !confirm('Chỉ tắt làm mờ khi đã có phê duyệt của ban giám hiệu và quy định rõ ràng về truy cập video. Tiếp tục?')) {
        e.target.checked = true;
        return;
      }
      applySettings({ blurFaces: e.target.checked });
    });

    document.addEventListener('click', (e) => {
      if (e.target.closest('[data-close]')) e.target.closest('dialog').close();
    });
  }

  /* --- Thống kê, nguồn video, camera --- */
  function updateStats() {
    const v = engine.view;
    $('#stPeople').textContent = v.people.length;
    $('#stZone').textContent = [...v.flagged].filter((k) => k[0] === 'p').length;
    $('#stObj').textContent = v.timers.size;
    $('#stCount').textContent = `${engine.counts.in} / ${engine.counts.out}`;
    $('#stFps').textContent = src.kind === 'demo' ? 'mô phỏng' : `${fps.toFixed(1)} fps`;
    $('#clock').textContent = new Date().toLocaleTimeString('vi-VN');
  }

  function bindSource() {
    const select = $('#source'), file = $('#fileInput');
    select.addEventListener('change', () => {
      if (select.value === 'file') file.click();
      else setSource(select.value);
    });
    file.addEventListener('change', () => {
      if (file.files[0]) setSource('file', file.files[0]);
      else select.value = src.kind;                                 // người dùng hủy chọn tệp
      file.value = '';
    });

    $('#demoActions').addEventListener('click', (e) => {
      const k = e.target.dataset.demo;
      if (k === 'crowd') Sim.spawnCrowd();
      else if (k) Sim.spawn(k);
    });

    $('#camTabs').addEventListener('click', (e) => {
      const btn = e.target.closest('.cam-tab');
      if (!btn || btn.dataset.id === camId) return;
      camId = btn.dataset.id;
      Store.set(KEY.cam, camId);
      if (tool.name) setTool(tool.name);
      renderZones(); renderCamTabs();
      setSource('demo');                                            // bản đầu: mỗi camera là một hồ sơ vùng riêng, nguồn quay về demo
    });
  }


  /* =======================================================
     11. KHỞI ĐỘNG
     ======================================================= */
  function init() {
    purgeOld();
    $$('.tool').forEach((b) => b.addEventListener('click', () => setTool(b.dataset.tool)));
    bindCanvas(); bindZones(); bindAlerts(); bindSettings(); bindSource();
    setTool(null);
    syncPrivacy(); renderZones(); renderAlerts();
    setSource('demo');
    setInterval(updateStats, 250);
    setInterval(purgeOld, 10 * 60 * 1000);
    requestAnimationFrame(frame);
  }

  init();
})();
