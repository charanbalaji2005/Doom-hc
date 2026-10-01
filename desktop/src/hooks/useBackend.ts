import { useEffect, useRef, useState } from 'react';
import { api, ApiError, resolveConnection } from '@/lib/api';

export type BackendStatus = { state: 'connecting' | 'online' | 'offline' | 'unauthorized' | 'unconfigured'; latencyMs?: number;
  localOnly?: boolean; robot?: boolean; hasProvider?: boolean; version?: string };

/** Polls /status; latency is the measured round trip of that request. Recovers automatically after restarts. */
export function useBackend(intervalMs = 4000): [BackendStatus, () => void] {
  const [s, setS] = useState<BackendStatus>({ state: 'connecting' });
  const tick = useRef(0);
  const check = async () => {
    if (!(await resolveConnection())) { setS({ state: 'unconfigured' }); return; }
    const t0 = performance.now();
    try {
      const r = await api<{ local_only: boolean; robot_connected: boolean; has_provider: boolean; version: string }>('/status');
      setS({ state: 'online', latencyMs: Math.round(performance.now() - t0), localOnly: r.local_only, robot: r.robot_connected, hasProvider: r.has_provider, version: r.version });
    } catch (e) {
      setS({ state: e instanceof ApiError && e.status === 401 ? 'unauthorized' : 'offline' });
    }
  };
  useEffect(() => {
    check();
    const id = setInterval(check, intervalMs);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, tick.current]);
  return [s, () => { tick.current++; check(); }];
}
