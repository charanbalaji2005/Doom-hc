import { useEffect, useRef, useState } from 'react';
import { Loader2, RotateCcw, Send, Square } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Markdown } from '@/components/Markdown';
import { useChat } from '@/hooks/useChat';
import { cn } from '@/lib/utils';

const STATUS_NOTE: Record<string, string> = { cancelled: 'Stopped', error: 'Failed', interrupted: 'Interrupted (app closed before it finished)' };

export function ChatPane({ conversationId, onConversation, compact = false }: { conversationId: string | null; onConversation?: (id: string) => void; compact?: boolean }) {
  const { messages, phase, error, send, retry, cancel } = useChat(conversationId, onConversation);
  const [draft, setDraft] = useState('');
  const end = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }); }, [messages]);
  const busy = phase === 'thinking' || phase === 'streaming';
  const submit = () => { const t = draft.trim(); if (!t || busy) return; setDraft(''); send(t); };
  const last = messages[messages.length - 1];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className={cn('flex-1 space-y-4 overflow-y-auto', compact ? 'px-3 py-3' : 'px-6 py-5')}>
        {messages.length === 0 && (
          <div className="mt-10 text-center text-sm text-graphite-500">Ask a question, paste code, or describe a task.</div>
        )}
        {messages.map(m => (
          <div key={m.id} className={cn('text-[14.5px]', m.role === 'user' ? 'ml-8 rounded-lg bg-graphite-800 px-3 py-2' : '')}>
            {m.role === 'assistant' && m.status === 'streaming' && !m.content
              ? <div className="flex items-center gap-2 text-graphite-500"><Loader2 size={14} className="animate-spin" />Thinking</div>
              : <Markdown text={m.content} onInsert={c => { setDraft(d => (d ? d + '\n' : '') + c); box.current?.focus(); }} />}
            {m.role === 'assistant' && m.status !== 'streaming' && (
              <div className="mt-1 flex flex-wrap items-center gap-x-3 text-xs text-graphite-500">
                {m.model && <span>{m.model}</span>}
                {typeof m.metrics?.ttft_ms === 'number' && <span>first token {Math.round(m.metrics.ttft_ms)} ms</span>}
                {typeof m.metrics?.tokens_per_s === 'number' && <span>{m.metrics.tokens_per_s} tokens/s</span>}
                {STATUS_NOTE[m.status] && <span className={m.status === 'error' ? 'text-danger' : 'text-amber'}>{STATUS_NOTE[m.status]}{m.error ? `: ${m.error.message}` : ''}</span>}
              </div>
            )}
          </div>
        ))}
        <div ref={end} />
      </div>
      {error && <div className="mx-3 mb-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">{error}</div>}
      <div className={cn('border-t border-graphite-800', compact ? 'p-2' : 'p-4')}>
        <div className="flex items-end gap-2">
          <textarea ref={box} value={draft} onChange={e => setDraft(e.target.value)} rows={compact ? 2 : 3}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); } if (e.key === 'Escape' && busy) cancel(); }}
            placeholder="Message Humanoid Companion" aria-label="Message"
            className="min-h-[44px] flex-1 resize-none rounded-md border border-graphite-700 bg-graphite-950 px-3 py-2 text-sm placeholder:text-graphite-500" />
          {busy
            ? <Button variant="secondary" size="icon" onClick={cancel} aria-label="Stop response" title="Stop (Esc)"><Square size={16} /></Button>
            : <Button size="icon" onClick={submit} disabled={!draft.trim()} aria-label="Send"><Send size={16} /></Button>}
        </div>
        {!busy && last?.role === 'assistant' && (
          <button className="mt-1.5 flex items-center gap-1 text-xs text-graphite-500 hover:text-ceramic" onClick={retry}><RotateCcw size={12} />Retry last reply</button>
        )}
      </div>
    </div>
  );
}
