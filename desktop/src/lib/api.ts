import { createSSEParser } from './sse';

export type Conn = { url: string; token: string };
export type Message = {
  id: string; conversation_id: string; seq: number; role: 'user' | 'assistant' | 'system' | 'tool'; content: string;
  status: 'complete' | 'streaming' | 'cancelled' | 'error' | 'interrupted'; model: string | null; provider_id: string | null;
  error: { code: string; message: string } | null; metrics: Record<string, number | string | null> | null; created_at: string;
};
export type Conversation = { id: string; title: string; archived: boolean; tags: string[]; created_at: string; updated_at: string; message_count?: number };
export type Provider = {
  id: string; name: string; kind: string; base_url: string; model: string; enabled: boolean; privacy: 'local' | 'remote';
  requires_network: boolean; has_api_key: boolean; capabilities: Record<string, boolean>;
};
export type AppSettings = {
  local_only: boolean; retention_days: number; system_prompt: string; max_context_tokens: number; max_response_tokens: number;
  default_provider_id: string | null; shortcut: string; auto_speak: boolean; store_audio: boolean;
};
export type HcEvent = { v: number; type: string; conversation_id: string; message_id: string; data: Record<string, unknown> };

export const inTauri = () => typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
let conn: Conn | null = null;

export async function resolveConnection(): Promise<Conn | null> {
  if (conn) return conn;
  if (inTauri()) {
    const { invoke } = await import('@tauri-apps/api/core');
    conn = await invoke<Conn>('backend_info');
    return conn;
  }
  const token = localStorage.getItem('hc.token');
  if (!token) return null;
  conn = { url: localStorage.getItem('hc.url') || 'http://127.0.0.1:8765', token };
  return conn;
}

export function setDevConnection(url: string, token: string) {
  const u = url.replace(/\/$/, '');
  localStorage.setItem('hc.url', u);
  localStorage.setItem('hc.token', token);
  conn = { url: u, token };
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message); }
}

export async function api<T>(path: string, opts: { method?: string; json?: unknown; signal?: AbortSignal } = {}): Promise<T> {
  const c = await resolveConnection();
  if (!c) throw new ApiError(0, 'no_connection', 'Not connected to the backend.');
  let r: Response;
  try {
    r = await fetch(c.url + path, {
      method: opts.method || (opts.json !== undefined ? 'POST' : 'GET'), signal: opts.signal,
      headers: { Authorization: `Bearer ${c.token}`, ...(opts.json !== undefined ? { 'Content-Type': 'application/json' } : {}) },
      body: opts.json !== undefined ? JSON.stringify(opts.json) : undefined,
    });
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e;
    throw new ApiError(0, 'offline', 'The backend is not reachable.');
  }
  if (r.status === 204) return undefined as T;
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(r.status, body?.error?.code || 'error', body?.error?.message || `HTTP ${r.status}`);
  return body as T;
}

export async function download(path: string, filename: string) {
  const c = await resolveConnection();
  if (!c) return;
  const r = await fetch(c.url + path, { headers: { Authorization: `Bearer ${c.token}` } });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(await r.blob());
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

/** POST a message and yield protocol events as they arrive. */
export async function* streamMessage(cid: string, body: Record<string, unknown>, signal?: AbortSignal): AsyncGenerator<HcEvent> {
  const c = await resolveConnection();
  if (!c) throw new ApiError(0, 'no_connection', 'Not connected to the backend.');
  const r = await fetch(`${c.url}/conversations/${cid}/messages`, {
    method: 'POST', signal, headers: { Authorization: `Bearer ${c.token}`, 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!r.ok) {
    const b = await r.json().catch(() => ({}));
    throw new ApiError(r.status, b?.error?.code || 'error', b?.error?.message || `HTTP ${r.status}`);
  }
  if ((r.headers.get('content-type') || '').includes('application/json')) {
    yield { v: 1, type: 'replayed', conversation_id: cid, message_id: '', data: await r.json() };
    return;
  }
  const reader = r.body!.getReader();
  const dec = new TextDecoder();
  const queue: HcEvent[] = [];
  const feed = createSSEParser(e => { try { queue.push(JSON.parse(e.data)); } catch { /* a malformed event is skipped, never fatal */ } });
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    feed(dec.decode(value, { stream: true }));
    while (queue.length) yield queue.shift()!;
  }
}
