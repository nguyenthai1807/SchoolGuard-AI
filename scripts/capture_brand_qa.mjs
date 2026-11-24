// Capture real desktop/mobile viewport evidence with Chrome DevTools Protocol.
// Uses an isolated temporary browser profile; does not touch personal Chrome.
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';

const root = process.cwd();
const runtime = path.join(root, 'runtime');
const evidence = path.join(root, 'docs', 'experiments');
const profile = fs.mkdtempSync(path.join(runtime, 'brand-qa-cdp-'));
const chrome = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const processChrome = spawn(chrome, [
  '--headless=new', '--disable-gpu', '--no-first-run',
  `--user-data-dir=${profile}`, '--remote-debugging-port=0', 'about:blank',
], { stdio: 'ignore', windowsHide: true });
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

try {
  let port;
  for (let i = 0; i < 80; i++) {
    const active = path.join(profile, 'DevToolsActivePort');
    if (fs.existsSync(active)) {
      port = Number(fs.readFileSync(active, 'utf8').split(/\r?\n/)[0]);
      break;
    }
    await delay(100);
  }
  if (!port) throw new Error('Chrome CDP did not become ready');
  const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const page = pages.find(p => p.type === 'page');
  if (!page) throw new Error('No Chrome page target');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, { once: true });
    ws.addEventListener('error', reject, { once: true });
  });
  let id = 0;
  const waiting = new Map();
  ws.addEventListener('message', event => {
    const message = JSON.parse(event.data);
    if (!message.id || !waiting.has(message.id)) return;
    const { resolve, reject } = waiting.get(message.id);
    waiting.delete(message.id);
    message.error ? reject(new Error(message.error.message)) : resolve(message.result);
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const nextId = ++id;
    waiting.set(nextId, { resolve, reject });
    ws.send(JSON.stringify({ id: nextId, method, params }));
  });
  await send('Page.enable');
  for (const [width, height, mobile, name, url, bellPreview] of [
    [1440, 900, false, 'lh25-store-desktop-20261025.png', 'http://127.0.0.1:8770/store', false],
    [390, 844, true, 'lh25-store-mobile-20261025.png', 'http://127.0.0.1:8770/store', false],
    [1440, 900, false, 'lh25-login-desktop-20261025.png', 'http://127.0.0.1:8770/', false],
    [390, 844, true, 'lh25-login-mobile-20261025.png', 'http://127.0.0.1:8770/', false],
    [1440, 900, false, 'lh25-bell-preview-desktop-20261025.png', 'http://127.0.0.1:8770/', true],
    [390, 844, true, 'lh25-bell-preview-mobile-20261025.png', 'http://127.0.0.1:8770/', true],
  ]) {
    await send('Emulation.setDeviceMetricsOverride', {
      width, height, deviceScaleFactor: 1, mobile,
    });
    await send('Emulation.setTouchEmulationEnabled', { enabled: mobile });
    await send('Page.navigate', { url });
    await delay(1200);
    if (bellPreview) {
      // A DOM-only visual preview. This is not a logged-in or functional QA run.
      await send('Runtime.evaluate', { expression: `document.querySelector('#login').hidden=true;
        document.querySelector('#shell').hidden=false;
        document.querySelector('#notification-count').hidden=false;
        document.querySelector('#notification-count').textContent='1';` });
    }
    const { result } = await send('Runtime.evaluate', {
      expression: '({width: innerWidth, scrollWidth: document.documentElement.scrollWidth, title: document.title, logoLoaded: (document.querySelector(".store-logo-photo") || document.querySelector(".intro-brand .brand-photo"))?.naturalWidth > 0})',
      returnByValue: true,
    });
    if (result.value.width !== width || result.value.scrollWidth > width || !result.value.logoLoaded) {
      throw new Error(`Layout failed ${width}px: ${JSON.stringify(result.value)}`);
    }
    const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
    const file = path.join(evidence, name);
    fs.writeFileSync(file, Buffer.from(shot.data, 'base64'));
    console.log(`${name}: ${JSON.stringify(result.value)}`);
  }
  ws.close();
} finally {
  processChrome.kill();
  await delay(500);
  const resolvedRoot = path.resolve(runtime);
  const resolvedProfile = path.resolve(profile);
  if (path.dirname(resolvedProfile) !== resolvedRoot ||
      !path.basename(resolvedProfile).startsWith('brand-qa-cdp-')) {
    throw new Error(`Refusing unsafe QA profile cleanup: ${resolvedProfile}`);
  }
  try {
    fs.rmSync(resolvedProfile, { recursive: true, force: true });
  } catch (error) {
    console.warn(`QA browser profile cleanup deferred: ${error.message}`);
  }
}
