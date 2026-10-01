import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError, streamMessage, type Conversation, type Message } from '@/lib/api';
import { uid } from '@/lib/utils';

export type Phase = 'idle' | 'thinking' | 'streaming' | 'error';

export function useChat(conversationId: string | null, onConversation?: (id: string) => void) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [phase, setPhase] = useState<Phase>('idle');
  const [error, setError] = useState<string | null>(null);
  const cid = useRef<string | null>(conversationId);
  const active = useRef<{ messageId: string | null; abort: AbortController } | null>(null);

  useEffect(() => {
    cid.current = conversationId;
    if (!conversationId) { setMessages([]); return; }
    api<{ messages: Message[] }>(`/conversations/${conversationId}`).then(c => setMessages(c.messages)).catch(e => setError((e as Error).message));
  }, [conversationId]);

  const run = useCallback(async (body: Record<string, unknown>, optimisticUser?: string) => {
    setError(null);
    if (!cid.current) {
      const c = await api<Conversation>('/conversations', { json: {} });
      cid.current = c.id;
      onConversation?.(c.id);
    }
    const now = new Date().toISOString();
    const tempA = 'pending-' + uid();
    setMessages(m => {
      let next = body.regenerate && m.length && m[m.length - 1].role === 'assistant' ? m.slice(0, -1) : m;
      if (optimisticUser !== undefined)
        next = [...next, { id: 'u-' + uid(), conversation_id: cid.current!, seq: 0, role: 'user', content: optimisticUser, status: 'complete', model: null, provider_id: null, error: null, metrics: null, created_at: now }];
      return [...next, { id: tempA, conversation_id: cid.current!, seq: 0, role: 'assistant', content: '', status: 'streaming', model: null, provider_id: null, error: null, metrics: null, created_at: now }];
    });
    const abort = new AbortController();
    active.current = { messageId: null, abort };
    setPhase('thinking');
    let aid = tempA;
    const patch = (fn: (m: Message) => Message) => setMessages(ms => ms.map(m => (m.id === aid ? fn(m) : m)));
    try {
      for await (const ev of streamMessage(cid.current!, body, abort.signal)) {
        if (ev.type === 'replayed') { const c = await api<{ messages: Message[] }>(`/conversations/${cid.current}`); setMessages(c.messages); break; }
        if (ev.type === 'assistant.started') {
          const real = ev.message_id;
          setMessages(ms => ms.map(m => (m.id === tempA ? { ...m, id: real, model: String(ev.data.model ?? '') } : m)));
          aid = real; active.current.messageId = real;
        } else if (ev.type === 'assistant.delta') {
          setPhase('streaming');
          patch(m => ({ ...m, content: m.content + String(ev.data.text ?? '') }));
        } else if (ev.type === 'assistant.completed' || ev.type === 'assistant.cancelled' || ev.type === 'assistant.failed') {
          const status = ev.type === 'assistant.completed' ? 'complete' : ev.type === 'assistant.cancelled' ? 'cancelled' : 'error';
          patch(m => ({ ...m, status, metrics: (ev.data.metrics as Message['metrics']) ?? null, error: (ev.data.error as Message['error']) ?? null }));
          if (status === 'error') setError((ev.data.error as { message?: string })?.message ?? 'The model failed.');
        }
      }
      setPhase('idle');
    } catch (e) {
      if ((e as Error).name === 'AbortError') { patch(m => ({ ...m, status: 'cancelled' })); setPhase('idle'); }
      else {
        setMessages(ms => ms.filter(m => m.id !== tempA));
        setError(e instanceof ApiError ? e.message : (e as Error).message);
        setPhase('error');
      }
    } finally { active.current = null; }
  }, [onConversation]);

  const send = useCallback((text: string) => run({ content: text, client_request_id: uid() }, text), [run]);
  const retry = useCallback(() => run({ regenerate: true }), [run]);
  const cancel = useCallback(async () => {
    const a = active.current;
    if (!a) return;
    if (a.messageId) {
      try { await api(`/messages/${a.messageId}/cancel`, { method: 'POST' }); } catch { /* fall through to abort */ }
      setTimeout(() => a.abort.abort(), 2000); // only if the server did not end the stream itself
    } else a.abort.abort();
  }, []);
  return { messages, phase, error, send, retry, cancel, conversationId: cid.current };
}
