import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { postJson, getJson, requestJson } = vi.hoisted(() => ({ postJson: vi.fn(), getJson: vi.fn(), requestJson: vi.fn() }));

vi.mock('./shared', async importOriginal => ({
  ...await importOriginal<typeof import('./shared')>(),
  isMockMode: () => false,
  postJson,
  getJson,
  requestJson,
}));

import { recordEvent, recordExposure, removePreferenceCompletely, clearPreferencesCompletely } from './interactionClient';
import { clearTokens, saveAccountId } from './shared';

describe('Recommendation feedback wire contract', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', { getItem: () => null, removeItem: vi.fn() });
    clearTokens();
    postJson.mockReset(); getJson.mockReset(); requestJson.mockReset();
  });
  afterEach(() => { clearTokens(); vi.unstubAllGlobals(); });

  it.each(['all', 'item'])('账号切换后停止后续偏好删除批次（%s）', async scope => {
    saveAccountId('A');
    requestJson.mockResolvedValue({ accepted: true, application_status: 'APPLIED', operations: [] });
    getJson.mockImplementationOnce(async () => {
      saveAccountId('B');
      return { items: [{ item_id: 'B001' }] };
    });
    const operation = scope === 'all' ? clearPreferencesCompletely() : removePreferenceCompletely('B001');
    await expect(operation).rejects.toMatchObject({ name: 'AuthSessionChangedError' });
    expect(requestJson).toHaveBeenCalledTimes(1);
  });

  it('clears long histories through multiple batches in one user action', async () => {
    requestJson.mockResolvedValueOnce({ operation_complete: false, items: [{ item_id: 'B001' }], operations: [{ accepted: true, application_status: 'APPLIED' }] })
      .mockResolvedValueOnce({ operation_complete: true, items: [], operations: [{ accepted: true, application_status: 'APPLIED' }] });
    getJson.mockResolvedValueOnce({ items: [{ item_id: 'B001' }] }).mockResolvedValueOnce({ items: [] });
    await clearPreferencesCompletely();
    expect(requestJson).toHaveBeenCalledTimes(2);
    expect(requestJson).toHaveBeenNthCalledWith(1, 'DELETE', '/recommend/preferences');
  });

  it('tracks a pending bulk reversal before clearing the remaining history', async () => {
    requestJson.mockResolvedValueOnce({ operation_complete: false, items: [{ item_id: 'B001' }], operations: [{ accepted: true, application_status: 'PENDING', feedback_id: 'pending-reversal' }] })
      .mockResolvedValueOnce({ operation_complete: true, items: [], operations: [] });
    getJson.mockResolvedValueOnce({ accepted: true, application_status: 'APPLIED' })
      .mockResolvedValueOnce({ items: [{ item_id: 'B001' }] }).mockResolvedValueOnce({ items: [] });
    await clearPreferencesCompletely();
    expect(getJson).toHaveBeenNthCalledWith(1, '/recommend/feedback/status/pending-reversal');
    expect(requestJson).toHaveBeenCalledTimes(2);
  });

  it('stops bulk clear when any reversal was rejected', async () => {
    requestJson.mockResolvedValue({ operation_complete: false, items: [{ item_id: 'B001' }], operations: [{ accepted: false, application_status: 'NOT_APPLICABLE' }] });
    await expect(clearPreferencesCompletely()).rejects.toThrow('未被接受');
    expect(requestJson).toHaveBeenCalledTimes(1);
    expect(getJson).not.toHaveBeenCalled();
  });

  it('does not report success from an empty stale clear response when preferences remain', async () => {
    requestJson.mockResolvedValue({ operation_complete: true, items: [], operations: [] });
    getJson.mockResolvedValue({ items: [{ item_id: 'B001' }] });
    await expect(clearPreferencesCompletely()).rejects.toThrow('尚未清空');
    expect(requestJson).toHaveBeenCalledTimes(20);
  });

  it('continues beyond twenty batches while the authoritative preference version progresses', async () => {
    requestJson.mockResolvedValue({ operation_complete: false, items: [{ item_id: 'B001' }], operations: [] });
    for (let version = 1; version <= 25; version += 1) getJson.mockResolvedValueOnce({ preference_version: version, items: [{ item_id: 'B001' }] });
    getJson.mockResolvedValueOnce({ preference_version: 26, items: [] });
    await clearPreferencesCompletely();
    expect(requestJson).toHaveBeenCalledTimes(26);
  });

  it('continues partial deletion until no preference remains', async () => {
    requestJson.mockResolvedValueOnce({ accepted: true, application_status: 'APPLIED', operation_complete: false })
      .mockResolvedValueOnce({ accepted: true, application_status: 'APPLIED', operation_complete: true });
    getJson.mockResolvedValueOnce({ items: [{ item_id: 'B001' }] }).mockResolvedValueOnce({ items: [] });
    await removePreferenceCompletely('B001');
    expect(requestJson).toHaveBeenCalledTimes(2);
  });

  it('resumes deletion after an asynchronous reversal restores an earlier preference', async () => {
    requestJson.mockResolvedValueOnce({ accepted: true, application_status: 'PENDING', feedback_id: 'reverse' })
      .mockResolvedValueOnce({ accepted: true, application_status: 'APPLIED', operation_complete: true });
    getJson.mockResolvedValueOnce({ application_status: 'APPLIED' })
      .mockResolvedValueOnce({ items: [{ item_id: 'B001' }] }).mockResolvedValueOnce({ items: [] });
    await removePreferenceCompletely('B001');
    expect(requestJson).toHaveBeenCalledTimes(2);
  });

  it('never reports complete deletion when every batch leaves a preference', async () => {
    requestJson.mockResolvedValue({ accepted: true, application_status: 'APPLIED' });
    getJson.mockResolvedValue({ items: [{ item_id: 'B001' }] });
    await expect(removePreferenceCompletely('B001')).rejects.toThrow('尚未全部删除');
  });

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
