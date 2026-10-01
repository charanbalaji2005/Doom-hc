import { useMemo, useState } from 'react';
import hljs from 'highlight.js/lib/common';
import { Check, Copy, CornerDownLeft } from 'lucide-react';

function CodeBlock({ lang, code, onInsert }: { lang: string; code: string; onInsert?: (s: string) => void }) {
  const [copied, setCopied] = useState(false);
  const html = useMemo(() => {
    try { return lang && hljs.getLanguage(lang) ? hljs.highlight(code, { language: lang }).value : hljs.highlightAuto(code).value; }
    catch { return code.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]!)); }
  }, [lang, code]);
  return (
    <div className="my-2 overflow-hidden rounded-md border border-graphite-700 bg-graphite-950">
      <div className="flex items-center justify-between border-b border-graphite-800 px-2 py-1 text-xs text-graphite-500">
        <span>{lang || 'code'}</span>
        <span className="flex gap-1">
          {onInsert && <button className="flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-graphite-800" onClick={() => onInsert(code)}><CornerDownLeft size={12} />Insert</button>}
          <button className="flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-graphite-800"
            onClick={() => navigator.clipboard.writeText(code).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1200); })}>
            {copied ? <Check size={12} /> : <Copy size={12} />}{copied ? 'Copied' : 'Copy'}
          </button>
        </span>
      </div>
      <pre className="overflow-x-auto p-3 text-[13px] leading-relaxed"><code className="hljs font-mono" dangerouslySetInnerHTML={{ __html: html }} /></pre>
    </div>
  );
}

/** Safe renderer: fenced code blocks get syntax highlighting; everything else stays plain text (no HTML injection). */
export function Markdown({ text, onInsert }: { text: string; onInsert?: (s: string) => void }) {
  const parts = useMemo(() => {
    const out: { kind: 'text' | 'code'; lang?: string; body: string }[] = [];
    const re = /```([\w+-]*)\n?([\s\S]*?)(```|$)/g;
    let last = 0, m: RegExpExecArray | null;
    while ((m = re.exec(text))) {
      if (m.index > last) out.push({ kind: 'text', body: text.slice(last, m.index) });
      out.push({ kind: 'code', lang: m[1], body: m[2].replace(/\n$/, '') });
      last = re.lastIndex;
      if (m[3] === '' || re.lastIndex === m.index) break;
    }
    if (last < text.length) out.push({ kind: 'text', body: text.slice(last) });
    return out;
  }, [text]);
  return <div>{parts.map((p, i) => p.kind === 'code'
    ? <CodeBlock key={i} lang={p.lang || ''} code={p.body} onInsert={onInsert} />
    : <p key={i} className="whitespace-pre-wrap leading-relaxed">{p.body}</p>)}</div>;
}
