import { describe, expect, it } from 'vitest';
import { createSSEParser, type RawSSE } from './sse';

describe('createSSEParser', () => {
  it('handles events split across arbitrary chunk boundaries', () => {
    const out: RawSSE[] = [];
    const feed = createSSEParser(e => out.push(e));
    const stream = 'event: assistant.delta\ndata: {"t":"he"}\n\nevent: assistant.delta\r\ndata: {"t":"llo"}\r\n\r\n';
    for (const ch of stream) feed(ch);
    expect(out).toEqual([{ event: 'assistant.delta', data: '{"t":"he"}' }, { event: 'assistant.delta', data: '{"t":"llo"}' }]);
  });
  it('joins multi-line data and ignores comments', () => {
    const out: RawSSE[] = [];
    const feed = createSSEParser(e => out.push(e));
    feed(': keepalive\n\ndata: a\ndata: b\n\n');
    expect(out).toEqual([{ event: 'message', data: 'a\nb' }]);
  });
});
