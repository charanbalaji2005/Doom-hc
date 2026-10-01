import type { BackendStatus } from '@/hooks/useBackend';
import { cn } from '@/lib/utils';

const LABEL: Record<BackendStatus['state'], string> = { connecting: 'Connecting', online: 'Online', offline: 'Backend offline, retrying',
  unauthorized: 'Token rejected', unconfigured: 'Not configured' };

export function StatusDot({ s }: { s: BackendStatus }) {
  return (
    <span className="flex items-center gap-1.5 text-xs text-graphite-300" role="status">
      <i className={cn('h-2 w-2 rounded-full', s.state === 'online' ? 'bg-emerald' : s.state === 'connecting' ? 'bg-amber' : 'bg-danger')} />
      {LABEL[s.state]}{s.state === 'online' && s.latencyMs !== undefined ? ` · ${s.latencyMs} ms` : ''}{s.localOnly ? ' · local only' : ''}
    </span>
  );
}
