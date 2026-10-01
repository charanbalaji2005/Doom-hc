import { useState } from 'react';
import { Activity, Bot, Cpu, History as HistoryIcon, MessageSquare, Plus, Settings as SettingsIcon } from 'lucide-react';
import { useBackend } from '@/hooks/useBackend';
import { cn } from '@/lib/utils';
import { ChatPane } from './ChatPane';
import { Diagnostics, History, Humanoid, Models, Settings } from './Panels';
import { StatusDot } from './StatusDot';

const NAV = [
  ['chat', 'Chat', MessageSquare], ['history', 'History', HistoryIcon], ['models', 'Models', Cpu],
  ['humanoid', 'Humanoid', Bot], ['settings', 'Settings', SettingsIcon], ['diagnostics', 'Diagnostics', Activity],
] as const;
type Tab = typeof NAV[number][0];

export function Workspace() {
  const [status] = useBackend();
  const [tab, setTab] = useState<Tab>('chat');
  const [cid, setCid] = useState<string | null>(null);
  const [chatKey, setChatKey] = useState(0);
  return (
    <div className="flex h-full">
      <nav className="flex w-52 shrink-0 flex-col border-r border-graphite-800 bg-graphite-950 p-3" aria-label="Workspace">
        <div className="mb-4 px-2"><div className="text-sm font-semibold tracking-wide">HUMANOID COMPANION</div><StatusDot s={status} /></div>
        {NAV.map(([id, label, Icon]) => (
          <button key={id} onClick={() => setTab(id)} aria-current={tab === id}
            className={cn('mb-0.5 flex items-center gap-2 rounded-md px-2 py-1.5 text-sm', tab === id ? 'bg-graphite-800 text-ceramic' : 'text-graphite-300 hover:bg-graphite-850')}>
            <Icon size={16} />{label}
          </button>
        ))}
        <div className="mt-auto px-2 text-xs text-graphite-500">{status.version ? `Backend ${status.version}` : ''}</div>
      </nav>
      <main className="min-w-0 flex-1 overflow-y-auto">
        {tab === 'chat' && (
          <div className="flex h-full flex-col">
            <div className="flex items-center justify-between border-b border-graphite-800 px-6 py-2">
              <span className="text-sm text-graphite-300">{cid ? 'Conversation' : 'New conversation'}</span>
              <button className="flex items-center gap-1 text-sm text-graphite-300 hover:text-ceramic" onClick={() => { setCid(null); setChatKey(k => k + 1); }}><Plus size={14} />New</button>
            </div>
            <div className="min-h-0 flex-1"><ChatPane key={`${chatKey}-${cid ?? ''}`} conversationId={cid} onConversation={setCid} /></div>
          </div>
        )}
        {tab === 'history' && <History onOpen={id => { setCid(id); setTab('chat'); }} />}
        {tab === 'models' && <Models />}
        {tab === 'humanoid' && <Humanoid />}
        {tab === 'settings' && <Settings />}
        {tab === 'diagnostics' && <Diagnostics />}
      </main>
    </div>
  );
}
