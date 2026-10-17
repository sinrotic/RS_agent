import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { clearTokens, postEventStream, saveRealAccessToken } from './shared';

describe('authenticated SSE transport', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', { getItem: () => null, removeItem: vi.fn() });
    clearTokens();
    saveRealAccessToken('access-token');
  });
  afterEach(() => { clearTokens(); vi.unstubAllGlobals(); });

  function streamedResponse(text: string) {
    const bytes = new TextEncoder().encode(text);
    return new Response(new ReadableStream({
      start(controller) {
        for (let index = 0; index < bytes.length; index += 3) controller.enqueue(bytes.slice(index, index + 3));
        controller.close();
      },
    }), { headers: { 'Content-Type': 'text/event-stream' } });
  }

  it('handles split UTF-8, CRLF boundaries and comment frames without losing events', async () => {
    const fetchMock = vi.fn().mockResolvedValue(streamedResponse(
      ': keepalive\r\n\r\nevent: answer_block\r\ndata: {"type":"text","content":"中文结果"}\r\n\r\n'
      + 'event: done\ndata: {"done":true}\n\n'));
    vi.stubGlobal('fetch', fetchMock);
    const events: unknown[] = [];
    await postEventStream('/agent/chat/stream', { user_message: '查询' }, (event, data) => events.push([event, data]));
    expect(events).toEqual([['answer_block', { type: 'text', content: '中文结果' }], ['done', { done: true }]]);
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/agent/chat/stream'), expect.objectContaining({
      credentials: 'include', headers: expect.objectContaining({ Authorization: 'Bearer access-token' }),
    }));
  });

  it('rejects a partial final frame rather than applying truncated JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamedResponse('event: answer_block\ndata: {"type":')));
    await expect(postEventStream('/agent/chat/stream', {}, vi.fn())).rejects.toThrow('incomplete event');
  });

  it('propagates callback errors and never retries an already-open stream', async () => {
    const fetchMock = vi.fn().mockResolvedValue(streamedResponse('event: error\ndata: {}\n\n'));
    vi.stubGlobal('fetch', fetchMock);
    await expect(postEventStream('/agent/chat/stream', {}, () => { throw new Error('failed'); })).rejects.toThrow('failed');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
