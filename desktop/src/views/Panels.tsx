import { useCallback, useEffect, useState } from 'react';
import { Archive, Download, Pencil, Trash2 } from 'lucide-react';
import { Button, Field, Input } from '@/components/ui/button';
import { api, download, inTauri, type AppSettings, type Conversation, type Provider } from '@/lib/api';
import { fmtTime } from '@/lib/utils';

function useLoad<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const reload = useCallback(() => { if (path) api<T>(path).then(d => { setData(d); setErr(null); }).catch(e => setErr((e as Error).message)); }, [path]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(reload, [reload, ...deps]);
  return { data, err, reload };
}

export function History({ onOpen }: { onOpen: (id: string) => void }) {
  const [archived, setArchived] = useState(false);
  const [q, setQ] = useState('');
  const list = useLoad<{ items: Conversation[]; total: number }>(`/conversations?archived=${archived}&limit=100`, [archived]);
  const [hits, setHits] = useState<{ conversation_id: string; title: string; snippet: string; kind: string }[] | null>(null);
  useEffect(() => {
    if (!q.trim()) { setHits(null); return; }
    const t = setTimeout(() => api<{ items: typeof hits }>(`/search?q=${encodeURIComponent(q)}`).then(r => setHits(r.items ?? [])), 200);
    return () => clearTimeout(t);
  }, [q]);
  const act = async (fn: () => Promise<unknown>) => { await fn(); list.reload(); };
  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <div className="flex gap-2">
        <Input placeholder="Search all messages and titles" value={q} onChange={e => setQ(e.target.value)} aria-label="Search history" />
        <Button variant="secondary" onClick={() => setArchived(a => !a)}>{archived ? 'Show active' : 'Show archived'}</Button>
      </div>
      {list.err && <p className="text-sm text-danger">{list.err}</p>}
      {hits ? (
        <ul className="divide-y divide-graphite-800">
          {hits.length === 0 && <li className="py-3 text-sm text-graphite-500">No matches.</li>}
          {hits.map((h, i) => (
            <li key={i}><button className="w-full py-3 text-left" onClick={() => onOpen(h.conversation_id)}>
              <div className="text-sm font-medium">{h.title}</div><div className="text-xs text-graphite-300">{h.snippet}</div></button></li>
          ))}
        </ul>
      ) : (
        <ul className="divide-y divide-graphite-800">
          {list.data?.items.length === 0 && <li className="py-3 text-sm text-graphite-500">{archived ? 'Nothing archived.' : 'No conversations yet.'}</li>}
          {list.data?.items.map(c => (
            <li key={c.id} className="flex items-center gap-2 py-2.5">
              <button className="min-w-0 flex-1 text-left" onClick={() => onOpen(c.id)}>
                <div className="truncate text-sm font-medium">{c.title}</div>
                <div className="text-xs text-graphite-500">{fmtTime(c.updated_at)} · {c.message_count ?? 0} messages</div>
              </button>
              <Button size="sm" variant="ghost" aria-label="Rename" onClick={() => { const t = prompt('Rename conversation', c.title); if (t?.trim()) act(() => api(`/conversations/${c.id}`, { method: 'PATCH', json: { title: t.trim() } })); }}><Pencil size={14} /></Button>
              <Button size="sm" variant="ghost" aria-label={archived ? 'Restore' : 'Archive'} onClick={() => act(() => api(`/conversations/${c.id}`, { method: 'PATCH', json: { archived: !archived } }))}><Archive size={14} /></Button>
              <Button size="sm" variant="ghost" aria-label="Export Markdown" onClick={() => download(`/conversations/${c.id}/export?format=md`, `${c.title}.md`)}><Download size={14} /></Button>
              <Button size="sm" variant="ghost" aria-label="Delete" onClick={() => { if (confirm(`Delete “${c.title}” permanently?`)) act(() => api(`/conversations/${c.id}`, { method: 'DELETE' })); }}><Trash2 size={14} /></Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Models() {
  const list = useLoad<{ items: Provider[]; kinds: Record<string, { default_url: string }> }>('/providers');
  const settings = useLoad<AppSettings>('/settings');
  const [form, setForm] = useState({ name: 'Local Ollama', kind: 'ollama', base_url: '', model: 'llama3.1:8b', api_key: '' });
  const [result, setResult] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const add = async () => {
    setErr(null);
    try { await api('/providers', { json: { ...form, base_url: form.base_url || undefined, api_key: form.api_key || undefined } }); setForm(f => ({ ...f, api_key: '' })); list.reload(); }
    catch (e) { setErr((e as Error).message); }
  };
  const validate = async (p: Provider) => {
    setResult(r => ({ ...r, [p.id]: 'Checking…' }));
    try { const h = await api<{ ok: boolean; detail: string; latency_ms: number }>(`/providers/${p.id}/validate`, { method: 'POST' }); setResult(r => ({ ...r, [p.id]: `${h.ok ? 'OK' : 'Failed'}: ${h.detail} (${h.latency_ms} ms)` })); }
    catch (e) { setResult(r => ({ ...r, [p.id]: (e as Error).message })); }
  };
  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <section className="space-y-2">
        <h2 className="text-base font-semibold">Configured models</h2>
        {list.data?.items.length === 0 && <p className="text-sm text-graphite-500">None yet. Add a local Ollama or llama.cpp server, or a hosted API, below.</p>}
        {list.data?.items.map(p => (
          <div key={p.id} className="rounded-lg border border-graphite-800 p-3">
            <div className="flex items-center justify-between gap-2">
              <div><div className="text-sm font-medium">{p.name} <span className="text-graphite-500">· {p.model}</span></div>
                <div className="text-xs text-graphite-500">{p.kind} · {p.base_url} · <span className={p.privacy === 'local' ? 'text-emerald' : 'text-amber'}>{p.privacy === 'local' ? 'runs locally' : 'sends data over the network'}</span>{p.has_api_key ? ' · key stored in OS keychain' : ''}</div></div>
              <div className="flex gap-1">
                <Button size="sm" variant="secondary" onClick={() => validate(p)}>Test</Button>
                <Button size="sm" variant={settings.data?.default_provider_id === p.id ? 'default' : 'secondary'} onClick={async () => { await api('/settings', { method: 'PUT', json: { default_provider_id: p.id } }); settings.reload(); }}>{settings.data?.default_provider_id === p.id ? 'Default' : 'Make default'}</Button>
                <Button size="sm" variant="ghost" aria-label="Remove" onClick={async () => { await api(`/providers/${p.id}`, { method: 'DELETE' }); list.reload(); }}><Trash2 size={14} /></Button>
              </div>
            </div>
            {result[p.id] && <p className="mt-2 text-xs text-graphite-300">{result[p.id]}</p>}
          </div>
        ))}
      </section>
      <section className="space-y-3 rounded-lg border border-graphite-800 p-4">
        <h2 className="text-base font-semibold">Add a model</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Name"><Input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Type"><select className="h-9 w-full rounded-md border border-graphite-700 bg-graphite-950 px-2 text-sm" value={form.kind} onChange={e => setForm({ ...form, kind: e.target.value })}>
            <option value="ollama">Ollama (local)</option><option value="openai_compatible">OpenAI-compatible (llama.cpp, vLLM, LM Studio, hosted)</option><option value="anthropic">Anthropic API</option></select></Field>
          <Field label="Endpoint" hint={`Leave empty for ${list.data?.kinds[form.kind]?.default_url ?? 'the default'}`}><Input value={form.base_url} onChange={e => setForm({ ...form, base_url: e.target.value })} /></Field>
          <Field label="Model identifier"><Input value={form.model} onChange={e => setForm({ ...form, model: e.target.value })} /></Field>
          <Field label="API key" hint="Stored in the operating system's credential store, never shown again."><Input type="password" value={form.api_key} onChange={e => setForm({ ...form, api_key: e.target.value })} /></Field>
        </div>
        {err && <p className="text-sm text-danger">{err}</p>}
        <Button onClick={add}>Add model</Button>
      </section>
    </div>
  );
}

export function Settings() {
  const s = useLoad<AppSettings>('/settings');
  const [draft, setDraft] = useState<AppSettings | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => { if (s.data) setDraft(s.data); }, [s.data]);
  if (!draft) return <div className="p-6 text-sm text-graphite-500">{s.err ?? 'Loading…'}</div>;
  const save = async () => {
    try {
      const out = await api<AppSettings>('/settings', { method: 'PUT', json: { local_only: draft.local_only, retention_days: draft.retention_days, system_prompt: draft.system_prompt,
        max_context_tokens: draft.max_context_tokens, max_response_tokens: draft.max_response_tokens, shortcut: draft.shortcut } });
      let note = 'Saved.';
      if (inTauri() && out.shortcut) {
        const { invoke } = await import('@tauri-apps/api/core');
        try { await invoke('set_shortcut', { accelerator: out.shortcut }); } catch (e) { note = `Saved, but the shortcut could not be registered: ${e}`; }
      } else if (!inTauri()) note = 'Saved. The global shortcut applies in the desktop app only.';
      setMsg(note); s.reload();
    } catch (e) { setMsg((e as Error).message); }
  };
  return (
    <div className="mx-auto max-w-2xl space-y-4 p-6">
      <label className="flex items-start gap-3 rounded-lg border border-graphite-800 p-3">
        <input type="checkbox" className="mt-1 accent-emerald" checked={draft.local_only} onChange={e => setDraft({ ...draft, local_only: e.target.checked })} />
        <span><span className="block text-sm font-medium">Local-only mode</span><span className="text-xs text-graphite-500">Remote providers are blocked before any network request is made. Enforced by the backend, not just hidden here.</span></span>
      </label>
      <Field label="Global shortcut" hint="Shows or hides the floating chat. Example: CommandOrControl+Shift+Space"><Input value={draft.shortcut} onChange={e => setDraft({ ...draft, shortcut: e.target.value })} /></Field>
      <Field label="Keep conversations for (days)" hint="0 keeps them until you delete them. Older conversations are removed at startup."><Input type="number" min={0} value={draft.retention_days} onChange={e => setDraft({ ...draft, retention_days: Number(e.target.value) })} /></Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Context budget (tokens, estimated)"><Input type="number" value={draft.max_context_tokens} onChange={e => setDraft({ ...draft, max_context_tokens: Number(e.target.value) })} /></Field>
        <Field label="Maximum reply (tokens)"><Input type="number" value={draft.max_response_tokens} onChange={e => setDraft({ ...draft, max_response_tokens: Number(e.target.value) })} /></Field>
      </div>
      <Field label="System prompt"><textarea className="h-28 w-full rounded-md border border-graphite-700 bg-graphite-950 p-2 text-sm" value={draft.system_prompt} onChange={e => setDraft({ ...draft, system_prompt: e.target.value })} /></Field>
      <div className="flex items-center gap-3"><Button onClick={save}>Save settings</Button>{msg && <span className="text-sm text-graphite-300">{msg}</span>}</div>
    </div>
  );
}

const QUICK: [string, Record<string, unknown>[]][] = [
  ['Wave', [{ type: 'gesture', name: 'wave', side: 'right' }]],
  ['Nod', [{ type: 'gesture', name: 'nod' }]],
  ['Look at me', [{ type: 'look_at', target: 'camera' }]],
  ['Smile', [{ type: 'expression', name: 'happy', duration_ms: 3000 }]],
  ['Red cube to green pad', [{ type: 'pick_up', object: 'red_cube' }, { type: 'place', target: 'green_pad' }]],
];

export function Humanoid() {
  const st = useLoad<{ connected: boolean; skills: string[]; state: Record<string, unknown> }>('/robot/status');
  const [log, setLog] = useState<string[]>([]);
  useEffect(() => { const id = setInterval(st.reload, 3000); return () => clearInterval(id); }, [st.reload]);
  const run = async (label: string, actions: Record<string, unknown>[]) => {
    setLog(l => [`${label}: sent`, ...l].slice(0, 20));
    try { const r = await api<{ status: string; result?: { detail?: string } }>('/robot/actions', { json: { actions, timeout_s: 60 } }); setLog(l => [`${label}: ${r.status}${r.result?.detail ? ` (${r.result.detail})` : ''}`, ...l].slice(0, 20)); }
    catch (e) { setLog(l => [`${label}: ${(e as Error).message}`, ...l].slice(0, 20)); }
  };
  return (
    <div className="mx-auto max-w-2xl space-y-4 p-6">
      <div className="rounded-lg border border-graphite-800 p-3 text-sm">
        {st.data?.connected ? <span className="text-emerald">HUMANOID X is connected ({st.data.skills.length} skills).</span>
          : <span className="text-graphite-300">Simulator not connected. Open <code className="font-mono">humanoid-x-live.html?bridge=ws://127.0.0.1:8765/robot/ws&amp;token=…</code> locally to connect it.</span>}
      </div>
      <div className="flex flex-wrap gap-2">
        {QUICK.map(([label, actions]) => <Button key={label} variant="secondary" disabled={!st.data?.connected} onClick={() => run(label, actions)}>{label}</Button>)}
        <Button variant="danger" onClick={() => api('/robot/estop', { method: 'POST' }).then(() => setLog(l => ['Emergency stop sent', ...l]))}>Emergency stop</Button>
      </div>
      <p className="text-xs text-graphite-500">Every request is checked against the skill schema, joint-safe ranges and the simulator's state before it is sent. Results come from the simulator itself.</p>
      <ul className="space-y-1 font-mono text-xs text-graphite-300">{log.map((l, i) => <li key={i}>{l}</li>)}</ul>
    </div>
  );
}

export function Diagnostics() {
  const d = useLoad<Record<string, unknown>>('/diagnostics?check_providers=true');
  return (
    <div className="mx-auto max-w-3xl space-y-3 p-6">
      <div className="flex items-center justify-between"><h2 className="text-base font-semibold">Diagnostics</h2><Button size="sm" variant="secondary" onClick={d.reload}>Refresh</Button></div>
      <p className="text-xs text-graphite-500">Values come from live checks and recorded responses. Anything not measured is listed as such.</p>
      {d.err && <p className="text-sm text-danger">{d.err}</p>}
      <pre className="overflow-x-auto rounded-md border border-graphite-800 bg-graphite-950 p-3 font-mono text-xs leading-relaxed">{d.data ? JSON.stringify(d.data, null, 2) : 'Loading…'}</pre>
    </div>
  );
}
