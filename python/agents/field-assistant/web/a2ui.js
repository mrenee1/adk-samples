// Minimal A2UI v0.9 renderer for this app's catalog.
//
// Handles the a2ui_operations envelope (createSurface, updateComponents,
// updateDataModel) and the components field_assistant/a2ui.py emits:
// Card, Column, Row, Text, TextField, Button, Notice, Divider, Image.
// Inputs write back to the surface's data model; Button actions resolve
// their context ({path} -> current value) and go to onAction(name, ctx).

const surfaces = new Map();

export function isEnvelope(obj) {
  return !!(obj && Array.isArray(obj.a2ui_operations));
}

function getPath(data, path, scope) {
  if (typeof path !== 'string') return undefined;
  const absolute = path.startsWith('/');
  let cur = absolute ? data : scope ?? data;
  for (const key of path.split('/').filter(Boolean)) {
    if (cur == null) return undefined;
    cur = cur[key];
  }
  return cur;
}

function setPath(data, path, value) {
  const keys = path.split('/').filter(Boolean);
  let cur = data;
  keys.slice(0, -1).forEach((k) => {
    if (typeof cur[k] !== 'object' || cur[k] === null) cur[k] = {};
    cur = cur[k];
  });
  cur[keys[keys.length - 1]] = value;
}

function resolve(value, surface, scope) {
  if (value && typeof value === 'object' && 'path' in value) {
    return getPath(surface.data, value.path, scope);
  }
  return value;
}

function applyOps(ops) {
  let touched = null;
  for (const op of ops) {
    if (op.createSurface) {
      const { surfaceId, catalogId } = op.createSurface;
      surfaces.set(surfaceId, { id: surfaceId, catalogId, components: new Map(), data: {} });
      touched = surfaceId;
    } else if (op.updateComponents) {
      const s = surfaces.get(op.updateComponents.surfaceId);
      if (!s) continue;
      op.updateComponents.components.forEach((c) => s.components.set(c.id, c));
      touched = s.id;
    } else if (op.updateDataModel) {
      const { surfaceId, path, value } = op.updateDataModel;
      const s = surfaces.get(surfaceId);
      if (!s) continue;
      if (!path || path === '/') s.data = structuredClone(value ?? {});
      else setPath(s.data, path, structuredClone(value));
      touched = s.id;
    }
  }
  return touched;
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function renderComponent(surface, id, ctx, scope) {
  const c = surface.components.get(id);
  if (!c) return null;
  const kids = (list) => {
    if (Array.isArray(list)) {
      return list.map((cid) => renderComponent(surface, cid, ctx, scope)).filter(Boolean);
    }
    if (list && list.componentId) {
      const items = getPath(surface.data, list.path, scope) || [];
      return items.map((item) => renderComponent(surface, list.componentId, ctx, item)).filter(Boolean);
    }
    return [];
  };

  switch (c.component) {
    case 'Card': {
      const e = el('div', 'a2-card');
      const child = renderComponent(surface, c.child, ctx, scope);
      if (child) e.append(child);
      return e;
    }
    case 'Column':
    case 'Row': {
      const e = el('div', c.component === 'Row' ? 'a2-row' : 'a2-col');
      if (c.justify) e.dataset.justify = c.justify;
      e.append(...kids(c.children));
      return e;
    }
    case 'Text': {
      const text = resolve(c.text, surface, scope);
      if (text == null || text === '') return null;
      const tag = { h1: 'h2', h2: 'h3', h3: 'h4' }[c.variant] || 'p';
      return el(tag, `a2-text a2-${c.variant || 'body'}`, String(text));
    }
    case 'Notice': {
      const text = resolve(c.text, surface, scope);
      if (!text) return null;
      return el('div', 'a2-notice', String(text));
    }
    case 'Divider':
      return el('hr', 'a2-divider');
    case 'Image': {
      const url = resolve(c.url, surface, scope);
      if (!url) return null;
      const img = el('img', 'a2-image');
      img.src = url;
      img.alt = '';
      return img;
    }
    case 'TextField': {
      const wrap = el('label', 'field');
      wrap.append(el('span', 'field-label', resolve(c.label, surface, scope) || ''));
      const input = c.multiline ? el('textarea') : el('input');
      if (!c.multiline) input.type = c.inputType || 'text';
      if (c.multiline) input.rows = 8;
      const bound = c.value && typeof c.value === 'object' && c.value.path;
      input.value = resolve(c.value, surface, scope) ?? '';
      if (bound) {
        input.addEventListener('input', () => setPath(surface.data, c.value.path, input.value));
      } else {
        input.readOnly = true;
      }
      wrap.append(input);
      return wrap;
    }
    case 'Button': {
      const action = c.action?.event;
      if (action?.name === 'open_url' && !resolve(action.context?.url, surface, scope)) {
        return null; // nothing to open
      }
      const btn = el('button', `btn ${c.variant === 'borderless' ? 'btn-ghost' : 'btn-primary'}`);
      btn.type = 'button';
      const label = renderComponent(surface, c.child, ctx, scope);
      btn.textContent = label ? label.textContent : 'OK';
      btn.addEventListener('click', async () => {
        if (!action) return;
        const context = {};
        for (const [k, v] of Object.entries(action.context || {})) {
          context[k] = resolve(v, surface, scope);
        }
        btn.disabled = true;
        try {
          await ctx.onAction(action.name, context, surface.id);
        } finally {
          btn.disabled = false;
        }
      });
      return btn;
    }
    default:
      return null; // unknown component: skip rather than break the sheet
  }
}

// Apply an envelope and return the rendered root element (or null).
export function renderEnvelope(envelope, ctx) {
  const id = applyOps(envelope.a2ui_operations);
  if (!id) return null;
  const surface = surfaces.get(id);
  const root = renderComponent(surface, 'root', ctx);
  if (!root) return null;
  const wrap = el('div', 'a2-surface');
  wrap.dataset.surfaceId = id;
  wrap.append(root);
  return wrap;
}

export function forgetSurface(id) {
  surfaces.delete(id);
}
