import { beforeEach, describe, expect, it, vi } from 'vitest';

const { postJson } = vi.hoisted(() => ({ postJson: vi.fn() }));

vi.mock('./shared', () => ({
  isMockMode: () => false,
  postJson,
}));

import { recordEvent, recordExposure } from './interactionClient';

describe('Recommendation feedback wire contract', () => {
  beforeEach(() => postJson.mockReset());

  it('sends the displayed item set as an exposure event', async () => {
    postJson.mockResolvedValue({ accepted: true, accepted_count: 2 });
    const request = {
      request_id: 'rec_req_001',
      session_id: 'sess_001',
      item_ids: ['B001', 'B002'],
      exposed_at: 1782636400000,
    };

    await recordExposure(request);

    expect(postJson).toHaveBeenCalledWith('/recommend/feedback/exposure', request);
  });

  it('sends why as a non-preference feedback event', async () => {
    postJson.mockResolvedValue({ accepted: true, accepted_count: 1, feedback_type: 'why' });
    const request = {
      request_id: 'rec_req_002',
      session_id: 'sess_002',
      item_id: 'B001',
      event_type: 'why' as const,
      occurred_at: 1782636410000,
    };

    await recordEvent(request);

    expect(postJson).toHaveBeenCalledWith('/recommend/feedback/event', request);
  });
});
