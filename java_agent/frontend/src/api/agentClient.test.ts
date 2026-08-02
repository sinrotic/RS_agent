import { beforeEach, describe, expect, it, vi } from 'vitest';

const { postJson } = vi.hoisted(() => ({ postJson: vi.fn() }));

vi.mock('./shared', () => ({
  isMockMode: () => false,
  mockDelay: vi.fn(),
  postJson,
}));

import { sendChat, toRecommendItems } from './agentClient';
import agentChatWireFixture from '../fixtures/agent-chat-wire.fixture.json';

describe('Agent chat wire contract', () => {
  beforeEach(() => postJson.mockReset());

  it('sends the formal snake_case request and reads the formal response', async () => {
    postJson.mockResolvedValue(agentChatWireFixture.response);

    await expect(sendChat(agentChatWireFixture.request)).resolves.toMatchObject({
      request_id: 'agent_req_001',
      turn_index: 1,
      assistant_message: '我会优先推荐通勤背包，并补充可解释证据。',
    });
    expect(postJson).toHaveBeenCalledWith('/agent/chat', agentChatWireFixture.request);
  });

  it('fails clearly when the server omits a required response field', async () => {
    postJson.mockResolvedValue({
      request_id: 'agent_req_001',
      session_id: 'sess_001',
      assistant_message: 'Incomplete response',
      recommended_items: [],
    });

    await expect(sendChat({
      session_id: 'sess_001',
      profile_user_id: 'A1XYZ',
      user_message: 'Find a backpack',
    })).rejects.toThrow('Agent response missing turn_index');
  });

  it('adapts Agent items to the shared recommendation display shape', () => {
    expect(toRecommendItems([{
      item_id: 'B001',
      title: 'Backpack',
      category: 'Backpacks',
      score: 0.91,
      reason: 'Matches commuting',
    }])).toEqual([expect.objectContaining({
      item_id: 'B001',
      rank: 1,
      score: 0.91,
      reason: 'Matches commuting',
      display: expect.objectContaining({ title: 'Backpack', category: 'Backpacks' }),
    })]);
  });
});
