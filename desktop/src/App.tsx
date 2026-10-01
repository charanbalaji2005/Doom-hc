import { useEffect, useState } from 'react';
import { Button, Field, Input } from '@/components/ui/button';
import { inTauri, resolveConnection, setDevConnection } from '@/lib/api';
import { MiniChat } from './views/MiniChat';
import { Workspace } from './views/Workspace';

function Connect({ onDone }: { onDone: () => void }) {
  const [url, setUrl] = useState('http://127.0.0.1:8765');
  const [token, setToken] = useState('');
  return (
    <div className="grid h-full place-items-center p-6">
      <div className="w-full max-w-sm space-y-3 rounded-xl border border-graphite-800 bg-graphite-950 p-5">
        <h1 className="text-lg font-semibold">Connect to the backend</h1>
        <p className="text-sm text-graphite-300">Browser development mode. The desktop app connects automatically. The token is in the <code>api_token</code> file in the backend's data folder.</p>
        <Field label="Backend URL"><Input value={url} onChange={e => setUrl(e.target.value)} /></Field>
        <Field label="API token"><Input type="password" value={token} onChange={e => setToken(e.target.value)} /></Field>
        <Button disabled={!token} onClick={() => { setDevConnection(url, token.trim()); onDone(); }}>Connect</Button>
      </div>
    </div>
  );
}

export default function App() {
  const [ready, setReady] = useState<boolean | null>(null);
  const [view, setView] = useState<'mini' | 'main'>(new URLSearchParams(location.search).get('view') === 'mini' ? 'mini' : 'main');
  useEffect(() => {
    resolveConnection().then(c => setReady(!!c)).catch(() => setReady(false));
    if (inTauri()) import('@tauri-apps/api/window').then(({ getCurrentWindow }) => { if (getCurrentWindow().label === 'mini') setView('mini'); });
  }, []);
  if (ready === null) return null;
  if (!ready) return <Connect onDone={() => setReady(true)} />;
  return view === 'mini' ? <MiniChat /> : <Workspace />;
}
