// Field Assistant phone app: Plan → Knock → Submit, plus Ask (the agent).
import {
  api, authHeaders, download, flushOutbox, hasGmail, initAuth, loadConfig,
  mailtoUrl, pendingCount, postVisit, saveGmailDraft, shrinkPhoto, signIn,
  signOut,
} from './api.js';
import { forgetSurface, isEnvelope, renderEnvelope } from './a2ui.js';
import { parseToolResult, runAgent, uid } from './agui.js';

const S = {
  cfg: null,
  me: null,
  settings: null,
  today: null,
  tab: localStorage.getItem('tab') || 'knock',
  chat: { threadId: uid(), messages: [], items: [] },
};
const $ = (sel, root = document) => root.querySelector(sel);

// ---------- tiny DOM helpers ----------

function h(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith('on')) e.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'class') e.className = v;
    else if (k === 'html') e.innerHTML = v;
    else e.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return e;
}

function toast(msg, action) {
  const t = $('#toast');
  t.replaceChildren(h('span', {}, msg));
  if (action) {
    t.append(h('button', { class: 'toast-btn', onclick: () => { t.hidden = true; action.run(); } }, action.label));
  }
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, action ? 7000 : 3500);
}

function fail(e) {
  console.error(e);
  toast(e.message || 'Something went wrong.');
}

// Bottom sheet: one at a time.
function openSheet(title, body, { onClose } = {}) {
  const sheet = $('#sheet');
  const close = () => {
    sheet.hidden = true;
    sheet.replaceChildren();
    document.body.classList.remove('sheet-open');
    onClose?.();
  };
  sheet.replaceChildren(
    h('div', { class: 'sheet-backdrop', onclick: close }),
    h('div', { class: 'sheet-panel', role: 'dialog', 'aria-label': title },
      h('div', { class: 'sheet-head' },
        h('h2', {}, title),
        h('button', { class: 'icon-btn', 'aria-label': 'Close', onclick: close }, '✕')),
      h('div', { class: 'sheet-body' }, body)),
  );
  sheet.hidden = false;
  document.body.classList.add('sheet-open');
  sheet.close = close;
  return close;
}
const closeSheet = () => $('#sheet').close?.();

function busy(text) {
  return h('div', { class: 'busy' }, h('span', { class: 'spinner' }), text);
}

const fmtDate = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
const outcomeLabel = (k) => (S.cfg.outcomes.find((o) => o.key === k) || { label: 'Earlier visit' }).label;
const mapsUrl = (address) => `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(address)}`;

// ---------- data ----------

async function refresh() {
  S.today = await api('/api/today');
  // Don't rebuild the chat (and lose what's being typed) for a data refresh.
  if (S.tab !== 'ask' || !$('#chat-log')) render();
}

// ---------- email ----------

function emailSheet(email, title = 'Email ready') {
  const box = h('div', { class: 'stack' },
    h('p', { class: 'muted' }, `To: ${email.to || '(no recipient: add one in Settings)'}${email.cc ? `  ·  Cc: ${email.cc}` : ''}`),
    h('p', { class: 'strong' }, email.subject),
    h('pre', { class: 'email-preview' }, email.body),
  );
  const actions = h('div', { class: 'stack' });
  if (hasGmail()) {
    actions.append(h('button', {
      class: 'btn btn-primary btn-block',
      onclick: async (ev) => {
        ev.target.disabled = true;
        try {
          await saveGmailDraft(email);
          closeSheet();
          toast('Saved to your Gmail drafts.', { label: 'Open Gmail', run: () => window.open('https://mail.google.com/mail/#drafts', '_blank') });
        } catch (e) {
          ev.target.disabled = false;
          toast(`${e.message}. Use "Open in email app" instead.`);
        }
      },
    }, 'Save to Gmail drafts'));
  }
  actions.append(
    h('a', { class: `btn ${hasGmail() ? 'btn-secondary' : 'btn-primary'} btn-block`, href: mailtoUrl(email), onclick: () => setTimeout(closeSheet, 300) }, 'Open in email app'),
    h('button', {
      class: 'btn btn-ghost btn-block',
      onclick: async () => {
        await navigator.clipboard.writeText(`${email.subject}\n\n${email.body}`);
        toast('Copied.');
      },
    }, 'Copy text'),
  );
  openSheet(title, h('div', { class: 'stack' }, box, actions));
}

// ---------- A2UI sheets (card, survey, ROE) ----------

async function onA2uiAction(name, ctx, surfaceId, where) {
  if (name === 'dismiss') {
    forgetSurface(surfaceId);
    if (where === 'sheet') closeSheet();
    else {
      S.chat.items = S.chat.items.filter((it) => it.el?.dataset.surfaceId !== surfaceId);
      renderChat();
    }
    return;
  }
  if (name === 'open_url') {
    window.open(ctx.url, '_blank', 'noopener');
    return;
  }
  if (name === 'open_email') {
    emailSheet(ctx);
    return;
  }
  try {
    const result = await api(`/api/actions/${name}`, { method: 'POST', body: { context: ctx } });
    forgetSurface(surfaceId);
    if (where === 'sheet') closeSheet();
    else {
      const item = S.chat.items.find((it) => it.el?.dataset.surfaceId === surfaceId);
      if (item) Object.assign(item, { kind: 'text', role: 'assistant', text: `✓ ${result.message}`, el: null });
      renderChat();
    }
    refresh().catch(fail);
    if (result.email) emailSheet(result.email);
    else if (result.url) toast(result.message, { label: 'Open form', run: () => window.open(result.url, '_blank', 'noopener') });
    else toast(result.message);
  } catch (e) {
    fail(e);
  }
}

async function workflowSheet(title, loadingText, path, body) {
  const holder = h('div', {}, busy(loadingText));
  openSheet(title, holder);
  try {
    const env = await api(path, { method: 'POST', body });
    const surface = renderEnvelope(env, { onAction: (n, c, id) => onA2uiAction(n, c, id, 'sheet') });
    holder.replaceChildren(surface || h('p', {}, 'Nothing to show.'));
  } catch (e) {
    holder.replaceChildren(h('p', { class: 'error' }, e.message));
  }
}

function pickPhoto() {
  return new Promise((resolve) => {
    const input = h('input', { type: 'file', accept: 'image/*', capture: 'environment', class: 'hidden' });
    input.addEventListener('change', () => resolve(input.files[0] || null), { once: true });
    document.body.append(input);
    input.click();
    setTimeout(() => input.remove(), 60_000);
  });
}

async function uploadPhoto(file) {
  const blob = await shrinkPhoto(file);
  const form = new FormData();
  form.append('file', blob, 'card.jpg');
  return (await api('/api/uploads', { method: 'POST', form })).upload_id;
}

async function scanCard(business) {
  const file = await pickPhoto();
  if (!file) return;
  const holder = h('div', {}, busy('Reading the card…'));
  openSheet('Business card', holder);
  try {
    const uploadId = await uploadPhoto(file);
    const env = await api('/api/workflows/card', { method: 'POST', body: { business_id: business.id, upload_id: uploadId } });
    holder.replaceChildren(renderEnvelope(env, { onAction: (n, c, id) => onA2uiAction(n, c, id, 'sheet') }) || h('p', {}, 'Nothing to show.'));
  } catch (e) {
    holder.replaceChildren(h('p', { class: 'error' }, e.message));
  }
}

const startRoe = (b) => workflowSheet('Right of Entry', 'Looking up the property owner…', '/api/workflows/roe', { business_id: b.id });
const startSurvey = (b) => workflowSheet('Site survey', 'Getting things ready…', '/api/workflows/survey', { business_id: b.id });
async function followupEmail(b) {
  try {
    emailSheet((await api('/api/workflows/followup-email', { method: 'POST', body: { business_id: b.id } })).email, 'Follow-up email');
  } catch (e) { fail(e); }
}

// ---------- Log a knock ----------

function defaultFollowup(outcome) {
  const days = S.cfg.outcomes.find((o) => o.key === outcome)?.followup_days;
  if (!days) return '';
  const d = new Date();
  d.setDate(d.getDate() + days);
  while (d.getDay() === 0 || d.getDay() === 6) d.setDate(d.getDate() + 1);
  return d.toLocaleDateString('en-CA'); // YYYY-MM-DD in local time
}

function knockSheet(business) {
  const st = { outcome: null, dm: false, card: false };
  const dm = h('input', { type: 'checkbox' });
  const card = h('input', { type: 'checkbox' });
  const notes = h('textarea', { rows: 2, placeholder: 'Who you talked to, what they said…' });
  const follow = h('input', { type: 'date' });
  const save = h('button', { class: 'btn btn-primary btn-block btn-lg', disabled: true }, 'Pick an outcome');
  const grid = h('div', { class: 'outcomes' });
  S.cfg.outcomes.forEach((o) => {
    const b = h('button', {
      class: `outcome outcome-${o.key}`,
      onclick: () => {
        st.outcome = o.key;
        grid.querySelectorAll('.outcome').forEach((x) => x.classList.toggle('selected', x === b));
        dm.checked = !!o.dm;
        follow.value = defaultFollowup(o.key);
        save.disabled = false;
        save.textContent = 'Save knock';
      },
    }, o.label);
    grid.append(b);
  });
  save.addEventListener('click', async () => {
    save.disabled = true;
    try {
      const { visit, queued } = await postVisit({
        business_id: business.id, outcome: st.outcome, dm: dm.checked,
        card: card.checked, notes: notes.value, followup_date: follow.value,
      });
      closeSheet();
      if (queued) {
        toast('No signal: saved on this phone, will send when you are back online.');
        updateOfflineBadge();
        return;
      }
      await refresh();
      const k = S.today.stats.knocks;
      toast(`Logged ${outcomeLabel(st.outcome)} · ${k} today`, {
        label: 'Undo',
        run: async () => { await api(`/api/visits/${visit.id}`, { method: 'DELETE' }); refresh(); },
      });
      if (card.checked) setTimeout(() => toast('Got a card?', { label: 'Scan it', run: () => scanCard(business) }), 400);
    } catch (e) {
      save.disabled = false;
      fail(e);
    }
  });
  openSheet(business.name, h('div', { class: 'stack' },
    business.restriction ? h('div', { class: 'restriction' }, '⚠ ', business.restriction) : null,
    grid,
    h('div', { class: 'toggles' },
      h('label', { class: 'toggle' }, dm, h('span', {}, 'Talked to decision maker')),
      h('label', { class: 'toggle' }, card, h('span', {}, 'Got their card'))),
    h('label', { class: 'field' }, h('span', { class: 'field-label' }, 'Notes (optional)'), notes),
    h('label', { class: 'field' }, h('span', { class: 'field-label' }, 'Follow up on'), follow),
    save,
  ));
}

// ---------- Business detail ----------

async function businessSheet(id) {
  const holder = h('div', {}, busy('Loading…'));
  openSheet('Business', holder);
  try {
    const b = await api(`/api/businesses/${id}`);
    holder.replaceChildren(h('div', { class: 'stack' },
      h('h3', {}, b.name),
      h('a', { href: mapsUrl(b.address), target: '_blank', class: 'muted' }, b.address || 'No address'),
      h('div', { class: 'chips' }, h('span', { class: 'chip' }, b.stage), b.next_followup ? h('span', { class: 'chip' }, `Follow up ${fmtDate(b.next_followup)}`) : null),
      b.restriction ? h('div', { class: 'restriction' }, '⚠ ', b.restriction) : null,
      b.notes ? h('p', { class: 'note' }, b.notes) : null,
      h('h4', {}, 'Contacts'),
      b.contacts.length ? h('ul', { class: 'list' }, b.contacts.map((c) => h('li', {},
        h('strong', {}, [c.first_name, c.last_name].filter(Boolean).join(' ') || '(no name)'),
        c.title ? ` · ${c.title}` : '',
        h('div', { class: 'muted' }, [c.phone, c.mobile, c.email].filter(Boolean).join(' · '))))) : h('p', { class: 'muted' }, 'None yet. Scan a card to add one.'),
      h('h4', {}, 'History'),
      b.visits.length ? h('ul', { class: 'list' }, b.visits.slice(0, 12).map((v) => h('li', {},
        h('strong', {}, `${fmtDate(v.date)} ${v.time || ''}`), ` · ${outcomeLabel(v.outcome)}${v.dm ? ' (DM)' : ''}`,
        v.notes ? h('div', { class: 'muted' }, v.notes) : null))) : h('p', { class: 'muted' }, 'No knocks yet.'),
      b.records.length ? h('div', {}, h('h4', {}, 'Surveys & ROEs'), h('ul', { class: 'list' }, b.records.map((r) => h('li', {}, `${fmtDate(r.date)} · ${r.kind === 'roe' ? 'ROE' : 'Site survey'} · ${r.status}`)))) : null,
      h('button', { class: 'btn btn-secondary btn-block', onclick: () => editBusiness(b) }, 'Edit details'),
    ));
  } catch (e) {
    holder.replaceChildren(h('p', { class: 'error' }, e.message));
  }
}

function editBusiness(b = {}, after) {
  const last = JSON.parse(localStorage.getItem('lastCity') || '{}');
  const f = (name, label, value, type = 'text') => h('label', { class: 'field' },
    h('span', { class: 'field-label' }, label),
    h('input', { name, type, value: value ?? '', autocomplete: 'off' }));
  const form = h('form', { class: 'stack' },
    f('name', 'Business name', b.name),
    f('street', 'Street address', b.street),
    h('div', { class: 'two' }, f('unit', 'Suite', b.unit), f('zip', 'ZIP', b.zip ?? last.zip, 'text')),
    f('city', 'City', b.city ?? last.city),
    h('div', { class: 'two' }, f('phone', 'Phone', b.phone, 'tel'), f('email', 'Email', b.email, 'email')),
    b.id ? h('label', { class: 'field' }, h('span', { class: 'field-label' }, 'Stage'),
      h('select', { name: 'stage' }, S.cfg.stages.map((s) => h('option', { value: s, selected: s === b.stage }, s)))) : null,
    b.id ? f('restriction', 'Contact restriction (e.g. do not email)', b.restriction) : null,
    b.id ? h('label', { class: 'field' }, h('span', { class: 'field-label' }, 'Notes'), h('textarea', { name: 'notes', rows: 3 }, b.notes || '')) : null,
    h('button', { class: 'btn btn-primary btn-block', type: 'submit' }, b.id ? 'Save' : 'Add business'),
  );
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const values = Object.fromEntries(new FormData(form));
    try {
      const saved = await api('/api/businesses', { method: 'POST', body: { ...values, id: b.id } });
      localStorage.setItem('lastCity', JSON.stringify({ city: values.city, zip: values.zip }));
      closeSheet();
      toast(b.id ? 'Saved.' : `Added ${saved.name}.`);
      await refresh();
      after?.(saved);
    } catch (e) { fail(e); }
  });
  openSheet(b.id ? 'Edit business' : 'New business', form);
}

// Find a business (or add a new one), then do something with it.
function findBusiness(title, onPick) {
  const q = h('input', { type: 'search', placeholder: 'Search name or street', autofocus: true });
  const results = h('ul', { class: 'list pick' });
  let timer;
  const search = async () => {
    const items = await api(`/api/businesses?q=${encodeURIComponent(q.value)}`);
    results.replaceChildren(...items.slice(0, 30).map((b) => h('li', {},
      h('button', { class: 'pick-row', onclick: () => onPick(b) },
        h('strong', {}, b.name), h('span', { class: 'muted' }, b.address)))));
  };
  q.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(search, 200); });
  openSheet(title, h('div', { class: 'stack' }, q,
    h('button', { class: 'btn btn-secondary btn-block', onclick: () => editBusiness({ name: q.value }, onPick) }, '+ New business'),
    results));
  search().catch(fail);
}

// ---------- Screens ----------

function progressBar(stats) {
  const pct = Math.min(100, Math.round((stats.knocks / stats.goal) * 100));
  return h('section', { class: 'progress-card' },
    h('div', { class: 'progress-top' },
      h('div', {}, h('span', { class: 'big' }, stats.knocks), h('span', { class: 'muted' }, ` / ${stats.goal} knocks`)),
      h('div', { class: 'mini-stats' },
        h('span', {}, h('b', {}, stats.dm), ' DM'),
        h('span', {}, h('b', {}, stats.followups), ' follow-ups'),
        h('span', {}, h('b', {}, stats.sales), ' sales'))),
    h('div', { class: 'bar' }, h('div', { class: 'bar-fill', style: `width:${pct}%` })),
  );
}

function stopCard(stop, i) {
  const b = stop.business;
  const done = stop.visits_today.length > 0;
  return h('article', { class: `stop ${done ? 'stop-done' : ''}` },
    h('div', { class: 'stop-head', onclick: () => businessSheet(b.id) },
      h('span', { class: 'stop-num' }, done ? '✓' : i + 1),
      h('div', { class: 'stop-title' },
        h('strong', {}, b.name),
        h('span', { class: 'muted' }, b.address)),
      h('span', { class: `chip chip-${b.stage.replace(/\s+/g, '-').toLowerCase()}` }, b.stage)),
    b.restriction ? h('div', { class: 'restriction' }, '⚠ ', b.restriction) : null,
    done ? h('div', { class: 'chips' }, stop.visits_today.map((v) => h('span', { class: 'chip chip-outcome' }, `${v.time} ${outcomeLabel(v.outcome)}${v.dm ? ' · DM' : ''}`))) : null,
    h('button', { class: `btn ${done ? 'btn-secondary' : 'btn-primary'} btn-block`, onclick: () => knockSheet(b) }, done ? 'Log another knock' : 'Log knock'),
    h('div', { class: 'quick' },
      h('button', { onclick: () => scanCard(b) }, '📇', h('span', {}, 'Card')),
      h('button', { onclick: () => startSurvey(b) }, '📋', h('span', {}, 'Survey')),
      h('button', { onclick: () => startRoe(b) }, '🏢', h('span', {}, 'ROE')),
      h('button', { onclick: () => followupEmail(b) }, '✉️', h('span', {}, 'Email')),
      b.phone ? h('a', { href: `tel:${b.phone}` }, '📞', h('span', {}, 'Call')) : h('a', { href: mapsUrl(b.address), target: '_blank' }, '🗺', h('span', {}, 'Map'))),
  );
}

function knockView() {
  const t = S.today;
  const stops = t.plan.stops;
  const dueNotPlanned = t.due.filter((d) => !stops.some((s) => s.business_id === d.business_id));
  return h('div', { class: 'stack' },
    progressBar(t.stats),
    dueNotPlanned.length ? h('button', { class: 'banner', onclick: () => setTab('plan') }, `🔔 ${dueNotPlanned.length} follow-up${dueNotPlanned.length > 1 ? 's' : ''} due today. Add to your plan →`) : null,
    stops.length || t.walk_ins.length ? null : h('div', { class: 'empty' },
      h('p', {}, 'No stops planned yet.'),
      h('button', { class: 'btn btn-primary', onclick: () => setTab('plan') }, 'Plan my day')),
    ...stops.map(stopCard),
    t.walk_ins.length ? h('h3', { class: 'section-title' }, 'Walk-ins') : null,
    ...t.walk_ins.map((s, i) => stopCard(s, stops.length + i)),
    h('button', { class: 'fab', onclick: () => findBusiness('Walk-in', (b) => { closeSheet(); knockSheet(b); }) }, '+ Walk-in'),
  );
}

async function savePlan(stops, start) {
  const plan = S.today.plan;
  await api('/api/plan', {
    method: 'PUT',
    body: {
      date: S.today.date,
      start: start ?? plan.start,
      stops: stops.map((s) => ({ business_id: s.business_id, core: s.core })),
    },
  });
  await refresh();
}

function routeLinks(start, stops) {
  // Google Maps takes up to 9 stops in between; split long days into legs.
  const addrs = stops.map((s) => s.business.address).filter(Boolean);
  const legs = [];
  let origin = start || null;
  for (let i = 0; i < addrs.length; i += 10) {
    const chunk = addrs.slice(i, i + 10);
    const dest = chunk[chunk.length - 1];
    const q = new URLSearchParams({ api: '1', destination: dest, travelmode: 'driving' });
    if (origin) q.set('origin', origin);
    if (chunk.length > 1) q.set('waypoints', chunk.slice(0, -1).join('|'));
    legs.push(`https://www.google.com/maps/dir/?${q}`);
    origin = dest;
  }
  return legs;
}

function planView() {
  const t = S.today;
  const stops = t.plan.stops;
  const start = h('input', { type: 'text', value: t.plan.start || '', placeholder: 'e.g. your first appointment or a coffee shop' });
  start.addEventListener('change', () => savePlan(stops, start.value).catch(fail));
  const move = (i, d) => {
    const next = [...stops];
    const [x] = next.splice(i, 1);
    next.splice(i + d, 0, x);
    savePlan(next).catch(fail);
  };
  const legs = routeLinks(t.plan.start, stops);

  const suggestBox = h('div', { class: 'stack' }, busy('Finding good stops…'));
  api('/api/suggestions').then((items) => {
    const planned = new Set(stops.map((s) => s.business_id));
    const fresh = items.filter((b) => !planned.has(b.id));
    const due = fresh.filter((b) => b.reason === 'Follow-up due');
    suggestBox.replaceChildren(...[
      due.length > 1 ? h('button', { class: 'btn btn-secondary btn-block', onclick: () => savePlan([...stops, ...due.map((b) => ({ business_id: b.id, core: true }))]).catch(fail) }, `Add all ${due.length} follow-ups due`) : null,
      fresh.length ? h('ul', { class: 'list' }, fresh.slice(0, 25).map((b) => h('li', { class: 'suggest' },
        h('div', {}, h('strong', {}, b.name), h('div', { class: 'muted' }, b.address || 'No address'), h('span', { class: 'chip' }, b.reason)),
        h('button', { class: 'btn btn-small btn-primary', onclick: () => savePlan([...stops, { business_id: b.id, core: true }]).catch(fail) }, 'Add')))) : h('p', { class: 'muted' }, 'Nothing to suggest. Search or add a business below.'),
    ].filter(Boolean));
  }).catch((e) => suggestBox.replaceChildren(h('p', { class: 'error' }, e.message)));

  return h('div', { class: 'stack' },
    h('section', { class: 'card' },
      h('label', { class: 'field' }, h('span', { class: 'field-label' }, 'Starting from'), start)),
    h('section', { class: 'card' },
      h('div', { class: 'row-between' }, h('h3', {}, `Today's stops (${stops.length})`),
        legs.length ? h('div', { class: 'chips' }, legs.map((url, i) => h('a', { class: 'btn btn-small btn-secondary', href: url, target: '_blank' }, legs.length > 1 ? `Route ${i + 1}` : 'Open route'))) : null),
      stops.length ? h('ol', { class: 'list plan-list' }, stops.map((s, i) => h('li', { class: 'plan-row' },
        h('div', { class: 'plan-name' }, h('strong', {}, s.business.name), h('span', { class: 'muted' }, s.business.address)),
        h('button', { class: `chip-btn ${s.core ? 'on' : ''}`, title: 'Must-do or if time allows', onclick: () => savePlan(stops.map((x, j) => (j === i ? { ...x, core: !x.core } : x))).catch(fail) }, s.core ? 'Must' : 'Maybe'),
        h('button', { class: 'icon-btn', 'aria-label': 'Move up', disabled: i === 0, onclick: () => move(i, -1) }, '↑'),
        h('button', { class: 'icon-btn', 'aria-label': 'Move down', disabled: i === stops.length - 1, onclick: () => move(i, 1) }, '↓'),
        h('button', { class: 'icon-btn', 'aria-label': 'Remove', onclick: () => savePlan(stops.filter((_, j) => j !== i)).catch(fail) }, '✕')))) : h('p', { class: 'muted' }, 'Add stops from the suggestions below.'),
      h('button', { class: 'btn btn-ghost btn-block', onclick: () => findBusiness('Add a stop', (b) => { closeSheet(); savePlan([...stops, { business_id: b.id, core: true }]).catch(fail); }) }, '+ Search all businesses')),
    h('section', { class: 'card' }, h('h3', {}, 'Suggested'), suggestBox),
    stops.length ? h('button', { class: 'btn btn-primary btn-block btn-lg', onclick: () => setTab('knock') }, 'Start knocking →') : null,
  );
}

function submitView() {
  const t = S.today;
  const s = t.stats;
  const sub = t.submission;
  const wins = h('textarea', { rows: 2, placeholder: 'Best conversation, a hot lead…' }, sub?.wins || '');
  const blockers = h('textarea', { rows: 2, placeholder: 'Anything you need help with?' }, sub?.blockers || '');
  const visited = new Set(s.visits.map((v) => v.business_id));
  const skipped = t.plan.stops.filter((x) => !visited.has(x.business_id));
  const tile = (n, label) => h('div', { class: 'tile' }, h('b', {}, n), h('span', {}, label));
  const btn = h('button', { class: 'btn btn-primary btn-block btn-lg' }, sub ? 'Send again' : 'Submit my day');
  btn.addEventListener('click', async () => {
    btn.disabled = true;
    try {
      const r = await api('/api/submit', { method: 'POST', body: { date: t.date, wins: wins.value, blockers: blockers.value } });
      await refresh();
      emailSheet(r.email, 'Send your report');
    } catch (e) { fail(e); btn.disabled = false; }
  });
  return h('div', { class: 'stack' },
    sub ? h('div', { class: 'success' }, `✓ Submitted ${new Date(sub.submitted_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`) : null,
    h('section', { class: 'tiles' },
      tile(`${s.knocks}/${s.goal}`, 'Knocks'), tile(s.dm, 'DM talks'), tile(s.followups, 'Follow-ups'),
      tile(s.interested, 'Interested'), tile(s.sales, 'Sales'), tile(s.cards, 'Cards'),
      tile(s.surveys, 'Surveys'), tile(s.roes, 'ROEs')),
    h('p', { class: 'muted center' }, `This week: ${t.week.knocks} knocks · ${t.week.dm} DM · ${t.week.sales} sales`),
    h('section', { class: 'card' }, h('h3', {}, `Today's knocks (${s.visits.length})`),
      s.visits.length ? h('ul', { class: 'list' }, s.visits.map((v) => h('li', {}, h('strong', {}, v.time), ` ${v.business_name} · ${outcomeLabel(v.outcome)}${v.dm ? ' (DM)' : ''}`, v.notes ? h('div', { class: 'muted' }, v.notes) : null))) : h('p', { class: 'muted' }, 'Nothing logged yet.'),
      skipped.length ? h('p', { class: 'muted' }, `Planned, not visited: ${skipped.map((x) => x.business.name).join(', ')}`) : null),
    h('label', { class: 'field' }, h('span', { class: 'field-label' }, 'Wins'), wins),
    h('label', { class: 'field' }, h('span', { class: 'field-label' }, 'Blockers / help needed'), blockers),
    btn,
    h('p', { class: 'muted center' }, S.settings.manager_email ? `Goes to ${S.settings.manager_email}` : 'Add your manager\'s email in Settings ⚙'),
  );
}

// ---------- Ask (the agent) ----------

function chatItem(item) {
  if (item.kind === 'surface') {
    // Render once and keep the element, so typed edits survive re-renders.
    item.el ||= renderEnvelope(item.env, { onAction: (n, c, id) => onA2uiAction(n, c, id, 'chat') }) || h('span');
    return item.el;
  }
  return h('div', { class: `bubble bubble-${item.role}` }, item.text || '…');
}

async function sendChat(text, extraNote) {
  const content = extraNote ? `${text}\n${extraNote}` : text;
  const msg = { id: uid(), role: 'user', content };
  S.chat.messages.push(msg);
  S.chat.items.push({ kind: 'text', role: 'user', text });
  const spinner = { kind: 'spinner' };
  S.chat.items.push(spinner);
  renderChat();
  const add = (item) => { S.chat.items.splice(S.chat.items.indexOf(spinner), 0, item); renderChat(); };
  const open = {}; // messageId -> { msg, item }
  try {
    await runAgent({
      url: '/api/agent',
      threadId: S.chat.threadId,
      messages: S.chat.messages,
      headers: await authHeaders(),
      onEvent: (ev) => {
        if (ev.type === 'TEXT_MESSAGE_START' || (ev.type === 'TEXT_MESSAGE_CONTENT' && !open[ev.messageId])) {
          const entry = { msg: { id: ev.messageId, role: 'assistant', content: '' }, item: { kind: 'text', role: 'assistant', text: '' } };
          open[ev.messageId] = entry;
          add(entry.item);
        }
        if (ev.type === 'TEXT_MESSAGE_CONTENT') {
          const { msg, item } = open[ev.messageId];
          msg.content += ev.delta;
          item.text = msg.content;
          renderChat();
        } else if (ev.type === 'TEXT_MESSAGE_END' && open[ev.messageId]) {
          S.chat.messages.push(open[ev.messageId].msg);
        } else if (ev.type === 'TOOL_CALL_RESULT') {
          const obj = parseToolResult(ev.content);
          if (isEnvelope(obj)) add({ kind: 'surface', env: obj });
        } else if (ev.type === 'RUN_ERROR') {
          add({ kind: 'text', role: 'assistant', text: `Sorry, that didn't work: ${ev.message}` });
        }
      },
    });
  } catch (e) {
    add({ kind: 'text', role: 'assistant', text: `Sorry, that didn't work: ${e.message}` });
  }
  S.chat.items = S.chat.items.filter((it) => it !== spinner && !(it.kind === 'text' && !it.text));
  renderChat();
  refresh().catch(() => {});
}

function renderChat() {
  const log = $('#chat-log');
  if (!log) return;
  log.replaceChildren(...S.chat.items.map((it) => (it.kind === 'spinner' ? h('div', { class: 'bubble bubble-assistant' }, busy('Thinking…')) : chatItem(it))));
  log.scrollTop = log.scrollHeight;
}

function askView() {
  const input = h('input', { type: 'text', placeholder: 'e.g. Log no answer at Sandbar Salon', enterkeyhint: 'send' });
  const form = h('form', { class: 'chat-input' },
    h('button', {
      type: 'button', class: 'icon-btn', 'aria-label': 'Scan a business card',
      onclick: async () => {
        const file = await pickPhoto();
        if (!file) return;
        try {
          const id = await uploadPhoto(file);
          sendChat(input.value || 'Scan this business card.', `upload_id=${id}`);
          input.value = '';
        } catch (e) { fail(e); }
      },
    }, '📷'),
    input,
    h('button', { type: 'submit', class: 'btn btn-primary' }, 'Send'));
  form.addEventListener('submit', (ev) => {
    ev.preventDefault();
    if (!input.value.trim()) return;
    sendChat(input.value.trim());
    input.value = '';
  });
  const chips = ['How am I doing today?', 'Who do I owe a follow-up?', 'Start an ROE for…'];
  const view = h('div', { class: 'chat' },
    h('div', { id: 'chat-log', class: 'chat-log' }),
    S.chat.items.length ? null : h('div', { class: 'chips center' }, chips.map((c) => h('button', {
      class: 'chip-btn',
      onclick: () => (c.endsWith('…') ? (input.value = c.replace('…', ' '), input.focus()) : sendChat(c)),
    }, c))),
    form);
  setTimeout(renderChat);
  return view;
}

// ---------- Settings ----------

function settingsSheet() {
  const s = S.settings;
  const f = (name, label, type = 'text', hint) => h('label', { class: 'field' },
    h('span', { class: 'field-label' }, label),
    type === 'textarea' ? h('textarea', { name, rows: 8 }, s[name] || '') : h('input', { name, type, value: s[name] ?? '' }),
    hint ? h('span', { class: 'hint' }, hint) : null);
  const form = h('form', { class: 'stack' },
    h('h3', {}, 'You'),
    f('rep_name', 'Your name'), f('rep_phone', 'Your phone', 'tel'), f('rep_email', 'Your email', 'email'),
    f('daily_goal', 'Daily knock goal', 'number'),
    f('manager_email', 'Manager email (daily report)', 'email'),
    h('h3', {}, 'ROE'),
    f('roe_to_name', 'Send ROEs to (name)'), f('roe_to_email', 'Their email', 'email'), f('roe_cc', 'Cc (optional)'),
    h('h3', {}, 'Site survey'),
    h('label', { class: 'field' }, h('span', { class: 'field-label' }, 'How you order a survey'),
      h('select', { name: 'survey_mode' }, [['email', 'Email a request'], ['form', 'Fill an online form'], ['log', 'Just record it']].map(([v, l]) => h('option', { value: v, selected: s.survey_mode === v }, l)))),
    f('survey_to_email', 'Survey request email', 'email'),
    f('survey_form_url', 'Survey form link', 'url', 'Optional. Can include {business}, {address}, {contact_name}, {contact_phone}.'),
    h('details', {}, h('summary', {}, 'Email templates'),
      h('p', { class: 'hint' }, 'Words in {curly braces} are filled in for you.'),
      f('roe_subject', 'ROE subject'), f('roe_body', 'ROE email', 'textarea'),
      f('survey_subject', 'Survey subject'), f('survey_body', 'Survey email', 'textarea'),
      f('followup_subject', 'Follow-up subject'), f('followup_body', 'Follow-up email', 'textarea')),
    h('button', { class: 'btn btn-primary btn-block', type: 'submit' }, 'Save settings'),
  );
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    try {
      S.settings = await api('/api/settings', { method: 'PUT', body: Object.fromEntries(new FormData(form)) });
      closeSheet();
      toast('Settings saved.');
      render();
    } catch (e) { fail(e); }
  });

  const file = h('input', { type: 'file', accept: '.xlsx,.csv,.json' });
  const city = h('input', { type: 'text', placeholder: 'Default city, e.g. Fernandina Beach' });
  const zip = h('input', { type: 'text', placeholder: 'Default ZIP', inputmode: 'numeric' });
  const importBtn = h('button', {
    class: 'btn btn-secondary btn-block',
    onclick: async () => {
      if (!file.files[0]) return toast('Choose your tracker file first.');
      const form2 = new FormData();
      form2.append('file', file.files[0]);
      form2.append('city', city.value);
      form2.append('zip_code', zip.value);
      importBtn.disabled = true;
      try {
        const r = await api('/api/import', { method: 'POST', form: form2 });
        toast(`Imported ${r.imported} businesses.`);
        await refresh();
      } catch (e) { fail(e); } finally { importBtn.disabled = false; }
    },
  }, 'Import tracker');

  openSheet('Settings', h('div', { class: 'stack' },
    form,
    h('hr'),
    h('h3', {}, 'Bring in your tracker'),
    h('p', { class: 'hint' }, 'Excel or CSV with a "Business" column (Address, City, Phone, Email, Contact, Status, Notes are picked up too). Importing again updates instead of duplicating.'),
    file, h('div', { class: 'two' }, city, zip), importBtn,
    h('hr'),
    h('h3', {}, 'Zoho CRM'),
    h('p', { class: 'hint' }, 'Download everything as Zoho import files, with step-by-step instructions inside.'),
    h('button', { class: 'btn btn-secondary btn-block', onclick: () => download('/api/export/zoho.zip', `zoho-import-${S.today.date}.zip`).catch(fail) }, 'Download for Zoho'),
    S.cfg.authMode === 'firebase' ? h('button', { class: 'btn btn-ghost btn-block', onclick: async () => { await signOut(); location.reload(); } }, `Sign out ${S.me}`) : null,
  ));
}

// ---------- Shell ----------

const TABS = [
  ['plan', 'Plan', '🗺'],
  ['knock', 'Knock', '🚪'],
  ['submit', 'Submit', '✅'],
  ['ask', 'Ask', '✨'],
];

function setTab(tab) {
  S.tab = tab;
  localStorage.setItem('tab', tab);
  render();
  window.scrollTo(0, 0);
}

function updateOfflineBadge() {
  const n = pendingCount();
  const b = $('#offline');
  b.hidden = !n && navigator.onLine;
  b.textContent = n ? `${n} knock${n > 1 ? 's' : ''} waiting for signal` : 'Offline';
}

function render() {
  if (!S.today) return;
  $('#date').textContent = fmtDate(S.today.date);
  $('#who').textContent = S.settings.rep_name || '';
  const views = { plan: planView, knock: knockView, submit: submitView, ask: askView };
  $('#main').replaceChildren(views[S.tab]());
  $('#tabs').replaceChildren(...TABS.map(([k, label, icon]) => h('button', {
    class: `tab ${S.tab === k ? 'active' : ''}`, onclick: () => setTab(k), 'aria-current': S.tab === k ? 'page' : null,
  }, h('span', { class: 'tab-icon' }, icon), label)));
  updateOfflineBadge();
}

async function start() {
  $('#settings').addEventListener('click', settingsSheet);
  window.addEventListener('online', async () => { const n = await flushOutbox(); if (n) { toast(`Sent ${n} saved knock${n > 1 ? 's' : ''}.`); refresh(); } updateOfflineBadge(); });
  window.addEventListener('offline', updateOfflineBadge);
  try {
    S.cfg = await loadConfig();
  } catch {
    $('#main').replaceChildren(h('p', { class: 'error' }, 'Can\'t reach the server. Check your connection.'));
    return;
  }
  await initAuth(async (user) => {
    if (!user) {
      $('#main').replaceChildren(h('div', { class: 'empty' },
        h('h2', {}, 'Field Assistant'),
        h('p', {}, 'Sign in with your work Google account.'),
        h('button', { class: 'btn btn-primary btn-lg', onclick: () => signIn().catch(fail) }, 'Sign in with Google')));
      return;
    }
    try {
      const me = await api('/api/me');
      S.me = me.user;
      S.settings = me.settings;
      await flushOutbox();
      await refresh();
      if (!S.settings.rep_name) setTimeout(() => { toast('Welcome! Add your name and emails first.', { label: 'Settings', run: settingsSheet }); }, 600);
    } catch (e) {
      $('#main').replaceChildren(h('p', { class: 'error' }, e.message));
    }
  });
}

if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
start();
