import { useState } from 'react';
import { Maximize2, X } from 'lucide-react';
import { useBackend } from '@/hooks/useBackend';
import { inTauri } from '@/lib/api';
import { ChatPane } from './ChatPane';
import { StatusDot } from './StatusDot';

async function tauriCall(cmd: 'open_workspace' | 'hide_mini') {
  if (!inTauri()) return;
  const { invoke } = await import('@tauri-apps/api/core');
  await invoke(cmd);
}

export function MiniChat() {
  const [status] = useBackend();
  const [cid, setCid] = useState<string | null>(() => localStorage.getItem('hc.mini.cid'));
  return (
    <div className="flex h-full flex-col overflow-hidden rounded-xl border border-graphite-700 bg-graphite-900">
      <header data-tauri-drag-region className="flex items-center justify-between border-b border-graphite-800 px-3 py-2">
        <div data-tauri-drag-region className="flex items-center gap-2">
          <div className="grid h-7 w-7 place-items-center rounded-full border border-graphite-700 bg-graphite-950"><span className="h-2 w-4 rounded-full bg-emerald" /></div>
          <div data-tauri-drag-region>
            <div className="text-sm font-semibold">Companion</div>
            <StatusDot s={status} />
          </div>
        </div>
        <div className="flex gap-1">
          <button className="rounded p-1.5 text-graphite-300 hover:bg-graphite-800" onClick={() => tauriCall('open_workspace')} aria-label="Open workspace" title="Open workspace"><Maximize2 size={15} /></button>
          <button className="rounded p-1.5 text-graphite-300 hover:bg-graphite-800" onClick={() => tauriCall('hide_mini')} aria-label="Hide" title="Hide (shortcut brings it back)"><X size={15} /></button>
        </div>
      </header>
      <div className="min-h-0 flex-1">
        <ChatPane compact conversationId={cid} onConversation={id => { setCid(id); localStorage.setItem('hc.mini.cid', id); }} />
      </div>
    </div>
  );
}
