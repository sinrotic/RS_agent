import { beforeEach, describe, expect, it, vi } from 'vitest';

const { postJson, postEventStream } = vi.hoisted(() => ({ postJson: vi.fn(), postEventStream: vi.fn() }));

vi.mock('./shared', async () => ({
  ...await vi.importActual<typeof import('./shared')>('./shared'),
  isMockMode: () => false,
  mockDelay: vi.fn(),
  postJson,
  postEventStream,
}));

import { mapAgentChatResponse, sendChat, streamChat } from './agentClient';

describe('Agent chat wire contract', () => {

  it('preserves a non-retryable stream conflict as a typed error', async () => {
    postEventStream.mockImplementation(async (_path, _request, onEvent) => onEvent('error', {
      status: 409, error_code: 'TURN_CONFLICT', retryable: false, message: 'private backend detail',
    }));
    await expect(streamChat('session', 'profile', '建议', vi.fn())).rejects.toMatchObject({ status: 409, retryable: false });
  });

  it('keeps only public degradation reasons', () => {
    expect(mapAgentChatResponse({ request_id: 'req', session_id: 'session', profile_user_id: 'profile', turn_index: 1,
      assistant_message: '继续描述需求', recommended_items: [],
      degradation_reasons: ['recommendation_unavailable', 'internal_error'] })).toMatchObject({
      degradationReasons: ['recommendation_unavailable'],
    });
  });

  it('receives the server request ID early and passes a cancellation signal to the stream', async () => {
    const started = vi.fn();
    const controller = new AbortController();
    postEventStream.mockImplementation(async (_path, _request, onEvent) => {
      onEvent('started', { request_id: 'running-request' });
      onEvent('interrupted', { reason: 'user_stop' });
    });
    await expect(streamChat('session', 'profile', '建议', vi.fn(), {}, {
      signal: controller.signal, onStarted: started,
    })).rejects.toMatchObject({ name: 'AgentInterruptedError' });
    expect(started).toHaveBeenCalledWith('running-request');
    expect(postEventStream.mock.calls[0][3]).toBe(controller.signal);
  });
  beforeEach(() => { postJson.mockReset(); postEventStream.mockReset(); });

  it('publishes streamed UI blocks before receiving the final response and sends current UI state', async () => {
    const block = { type: 'a2ui', messages: [{ version: 'v0.9', updateDataModel: {
      surfaceId: 'shopping', path: '/summary', value: '查询完成',
    } }] };
    const onBlock = vi.fn();
    postEventStream.mockImplementation(async (_path, _request, onEvent) => {
      onEvent('answer_block', block);
      expect(onBlock).toHaveBeenCalledWith(block);
      onEvent('done', { done: true, response: {
        request_id: 'req-1', session_id: 'session', profile_user_id: 'profile', turn_index: 1,
        assistant_message: '请查看结果', recommended_items: [], tool_calls: [], answer_blocks: [block],
      } });
    });
    const result = await streamChat('session', 'profile', '查找耳机', onBlock, { a2ui_state: [] });
    expect(result.answerBlocks).toEqual([block]);
    expect(postEventStream).toHaveBeenCalledWith('/agent/chat/stream', expect.objectContaining({
      context: { scene: 'agent_chat', a2ui_state: [] },
    }), expect.any(Function), undefined);
    expect(onBlock).toHaveBeenCalledTimes(1);
  });

  it('does not silently accept a disconnected or failed stream', async () => {
    postEventStream.mockResolvedValue(undefined);
    await expect(streamChat('session', 'profile', '查询', vi.fn())).rejects.toThrow('before completion');
    postEventStream.mockImplementation(async (_path, _request, onEvent) => onEvent('error', {}));
    await expect(streamChat('session', 'profile', '查询', vi.fn())).rejects.toThrow('对话未完成');
  });

  it('sends the formal snake_case request and maps the formal response', async () => {
    postJson.mockResolvedValue({
      request_id: 'agent_req_001',
      session_id: 'sess_001',
      profile_user_id: 'A1XYZ',
      turn_index: 1,
      assistant_message: '我会优先推荐通勤背包，并补充可解释证据。',
      recommended_items: [],
      tool_calls: [],
    });

    await expect(sendChat('sess_001', 'A1XYZ', 'Find a backpack')).resolves.toMatchObject({
      requestId: 'agent_req_001',
      sessionId: 'sess_001',
      profileUserId: 'A1XYZ',
      turnIndex: 1,
      assistantMessage: '我会优先推荐通勤背包，并补充可解释证据。',
    });
    expect(postJson).toHaveBeenCalledWith('/agent/chat', {
      session_id: 'sess_001',
      profile_user_id: 'A1XYZ',
      user_message: 'Find a backpack',
      limit: 5,
      context: { scene: 'agent_chat' },
    });
  });

  it('fails clearly when the server omits a required response field', async () => {
    postJson.mockResolvedValue({
      request_id: 'agent_req_001',
      session_id: 'sess_001',
      profile_user_id: 'A1XYZ',
      assistant_message: 'Incomplete response',
      recommended_items: [],
      tool_calls: [],
    });

    await expect(sendChat('sess_001', 'A1XYZ', 'Find a backpack')).rejects.toThrow('Agent response missing turn_index');
  });

  it('maps Agent items to the shared recommendation display shape', () => {
    expect(mapAgentChatResponse({
      request_id: 'agent-1',
      session_id: 'session-1',
      profile_user_id: 'user-1',
      card_set_id: 'rec-1',
      turn_index: 1,
      assistant_message: 'Here are the matches.',
      recommended_items: [{
        item_id: 'B001',
        title: 'Backpack',
        category: 'Backpacks',
        score: 0.91,
        reason: 'Matches commuting',
      }],
      tool_calls: [],
    })).toMatchObject({
      cardSetId: 'rec-1',
      items: [expect.objectContaining({
        item_id: 'B001',
        rank: 1,
        score: 0.91,
        reason: 'Matches commuting',
        display: expect.objectContaining({ title: 'Backpack', category: 'Backpacks' }),
      })],
    });
  });
});
