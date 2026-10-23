// Small AG-UI client: POST a RunAgentInput, read the SSE event stream.
// Events used by the app: TEXT_MESSAGE_START/CONTENT/END, TOOL_CALL_START,
// TOOL_CALL_RESULT (where A2UI envelopes arrive), RUN_FINISHED, RUN_ERROR.

export function uid() {
  return crypto.randomUUID ? crypto.randomUUID() : String(Date.now() + Math.random());
}

export async function runAgent({ url, threadId, messages, headers = {}, onEvent, signal }) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', ...headers },
    body: JSON.stringify({
      threadId,
      runId: uid(),
      state: {},
      messages,
      tools: [],
      context: [],
      forwardedProps: {},
    }),
    signal,
  });
  if (!res.ok || !res.body) {
    let detail = `${res.status}`;
    try { detail = (await res.json()).detail || detail; } catch { /* not JSON */ }
    throw new Error(detail);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let cut;
    while ((cut = buf.indexOf('\n\n')) >= 0) {
      const frame = buf.slice(0, cut);
      buf = buf.slice(cut + 2);
      const data = frame
        .split('\n')
        .filter((l) => l.startsWith('data:'))
        .map((l) => l.slice(5).replace(/^ /, ''))
        .join('\n');
      if (!data) continue; // keep-alive ping
      try {
        onEvent(JSON.parse(data));
      } catch (e) {
        console.warn('Bad AG-UI frame', e, data);
      }
    }
  }
}

// Tool results arrive as JSON strings; ADK sometimes wraps them as
// {"result": "<json>"}. Return the parsed object (or null).
export function parseToolResult(content) {
  let obj = content;
  for (let i = 0; i < 3 && typeof obj === 'string'; i++) {
    try { obj = JSON.parse(obj); } catch { return null; }
  }
  if (obj && typeof obj === 'object' && !obj.a2ui_operations && typeof obj.result === 'string') {
    return parseToolResult(obj.result);
  }
  return obj;
}
