// Talking to the server: sign-in, JSON calls, offline queue, Gmail drafts.

const FIREBASE = 'https://www.gstatic.com/firebasejs/10.12.2';
const GMAIL_SCOPE = 'https://www.googleapis.com/auth/gmail.compose';

let config = null;
let fb = null; // { auth, mod } once Firebase is loaded

export async function loadConfig() {
  const res = await fetch('/api/config');
  config = await res.json();
  return config;
}

// ---- Sign-in (only when the server runs with AUTH_MODE=firebase) ----

export async function initAuth(onChange) {
  if (config.authMode !== 'firebase') {
    onChange({ email: 'local' });
    return;
  }
  const appMod = await import(`${FIREBASE}/firebase-app.js`);
  const mod = await import(`${FIREBASE}/firebase-auth.js`);
  const app = appMod.initializeApp(config.firebase);
  const auth = mod.getAuth(app);
  fb = { auth, mod };
  try {
    const r = await mod.getRedirectResult(auth);
    if (r) keepGmailToken(mod.GoogleAuthProvider.credentialFromResult(r));
  } catch (e) {
    console.warn(e);
  }
  mod.onAuthStateChanged(auth, (user) => onChange(user));
}

function keepGmailToken(cred) {
  if (cred?.accessToken) {
    sessionStorage.setItem('gmailToken', cred.accessToken);
    sessionStorage.setItem('gmailTokenAt', String(Date.now()));
  }
}

export async function signIn() {
  const { auth, mod } = fb;
  const provider = new mod.GoogleAuthProvider();
  provider.addScope(GMAIL_SCOPE);
  provider.setCustomParameters({ prompt: 'select_account' });
  try {
    const r = await mod.signInWithPopup(auth, provider);
    keepGmailToken(mod.GoogleAuthProvider.credentialFromResult(r));
  } catch (e) {
    if (String(e.code).includes('popup')) return mod.signInWithRedirect(auth, provider);
    throw e;
  }
}

export async function signOut() {
  sessionStorage.removeItem('gmailToken');
  if (fb) await fb.mod.signOut(fb.auth);
}

export async function authHeaders() {
  if (!fb?.auth.currentUser) return {};
  return { Authorization: `Bearer ${await fb.auth.currentUser.getIdToken()}` };
}

// ---- JSON API ----

export async function api(path, { method = 'GET', body, form } = {}) {
  const headers = await authHeaders();
  const opts = { method, headers };
  if (form) opts.body = form;
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = `Something went wrong (${res.status}).`;
    try { msg = (await res.json()).detail || msg; } catch { /* not JSON */ }
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  const type = res.headers.get('content-type') || '';
  return type.includes('json') ? res.json() : res.blob();
}

// ---- Offline queue for knocks (no signal inside a building is normal) ----

const OUTBOX = 'outbox.v1';

function readOutbox() {
  try { return JSON.parse(localStorage.getItem(OUTBOX) || '[]'); } catch { return []; }
}

export function pendingCount() {
  return readOutbox().length;
}

export async function postVisit(visit) {
  try {
    return { visit: await api('/api/visits', { method: 'POST', body: visit }), queued: false };
  } catch (e) {
    if (e.status) throw e; // the server said no: don't queue
    const box = readOutbox();
    box.push({ ...visit, queued_at: new Date().toISOString() });
    localStorage.setItem(OUTBOX, JSON.stringify(box));
    return { visit: null, queued: true };
  }
}

export async function flushOutbox() {
  const box = readOutbox();
  if (!box.length) return 0;
  const left = [];
  let sent = 0;
  for (const v of box) {
    try {
      await api('/api/visits', { method: 'POST', body: v });
      sent++;
    } catch (e) {
      if (!e.status) left.push(v); // still offline; drop server rejections
    }
  }
  localStorage.setItem(OUTBOX, JSON.stringify(left));
  return sent;
}

// ---- Email: Gmail draft when signed in with Google, else the mail app ----

export function hasGmail() {
  const at = Number(sessionStorage.getItem('gmailTokenAt') || 0);
  return !!sessionStorage.getItem('gmailToken') && Date.now() - at < 55 * 60 * 1000;
}

function b64url(str) {
  const bytes = new TextEncoder().encode(str);
  let bin = '';
  bytes.forEach((b) => { bin += String.fromCharCode(b); });
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function mimeHeader(s) {
  // RFC 2047 so subjects with emoji/accents survive.
  return /^[\x20-\x7e]*$/.test(s) ? s : `=?UTF-8?B?${btoa(String.fromCharCode(...new TextEncoder().encode(s)))}?=`;
}

export async function saveGmailDraft({ to, cc, subject, body }) {
  const raw = [
    to ? `To: ${to}` : null,
    cc ? `Cc: ${cc}` : null,
    `Subject: ${mimeHeader(subject || '')}`,
    'MIME-Version: 1.0',
    'Content-Type: text/plain; charset=UTF-8',
    'Content-Transfer-Encoding: 8bit',
    '',
    body || '',
  ].filter((l) => l !== null).join('\r\n');
  const res = await fetch('https://gmail.googleapis.com/gmail/v1/users/me/drafts', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${sessionStorage.getItem('gmailToken')}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ message: { raw: b64url(raw) } }),
  });
  if (!res.ok) {
    if (res.status === 401) sessionStorage.removeItem('gmailToken');
    throw new Error(`Gmail said ${res.status}`);
  }
  return res.json();
}

export function mailtoUrl({ to, cc, subject, body }) {
  const q = new URLSearchParams();
  if (cc) q.set('cc', cc);
  if (subject) q.set('subject', subject);
  if (body) q.set('body', body);
  return `mailto:${encodeURIComponent(to || '')}?${q.toString().replace(/\+/g, '%20')}`;
}

export async function download(path, filename) {
  const blob = await api(path);
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

// Shrink phone photos (often 4-8 MB) to ~200 KB before upload.
export async function shrinkPhoto(file, maxSide = 1600) {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  return new Promise((ok) => canvas.toBlob(ok, 'image/jpeg', 0.82));
}
