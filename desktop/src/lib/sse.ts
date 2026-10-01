export type RawSSE = { event: string; data: string };

/** Incremental Server-Sent Events parser; feed it decoded text chunks of any size. */
export function createSSEParser(onEvent: (ev: RawSSE) => void) {
  let buf = '';
  return (chunk: string) => {
    buf = (buf + chunk).replace(/\r\n/g, '\n'); // normalise across chunk boundaries too
    let i: number;
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const raw = buf.slice(0, i);
      buf = buf.slice(i + 2);
      let event = 'message';
      const data: string[] = [];
      for (const line of raw.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
      }
      if (data.length) onEvent({ event, data: data.join('\n') });
    }
  };
}
