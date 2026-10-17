import { RecommendExposureFeedbackRequest, RecommendEventFeedbackRequest, RecommendFeedbackAckVO } from '../types/interaction';
import { isMockMode, postJson, getJson, requestJson, captureAuthSession, assertCurrentAuthSession } from './shared';
import { RecommendPreferencesVO, RecommendPreferenceClearVO } from '../types/interaction';

export async function recordExposure(req: RecommendExposureFeedbackRequest): Promise<RecommendFeedbackAckVO> {
  if (isMockMode()) {
    return {
      feedback_id: `expose-${Math.random().toString(36).substring(2, 9)}`,
      accepted: true,
      feedback_type: 'EXPOSURE',
      accepted_count: req.items?.length ?? req.item_ids?.length ?? 0,
      duplicate: false,
      application_status: 'NOT_APPLICABLE',
      preference_version: 0
    };
  }

  // Real request to Java Endpoint: rs-service-recommend -> POST /api/recommend/feedback/exposure
  return postJson<RecommendFeedbackAckVO>('/recommend/feedback/exposure', req);
}

export async function recordEvent(req: RecommendEventFeedbackRequest): Promise<RecommendFeedbackAckVO> {
  if (isMockMode()) {
    return {
      feedback_id: `event-${Math.random().toString(36).substring(2, 9)}`,
      accepted: true,
      feedback_type: req.event_type.toUpperCase(),
      accepted_count: 1,
      duplicate: false,
      application_status: req.event_type === 'like' || req.event_type === 'dislike' ? 'APPLIED' : 'NOT_APPLICABLE',
      preference_version: req.event_type === 'like' || req.event_type === 'dislike' ? 1 : 0
    };
  }

  // Real request to Java Endpoint: rs-service-recommend -> POST /api/recommend/feedback/event
  return postJson<RecommendFeedbackAckVO>('/recommend/feedback/event', req);
}

export async function reverseFeedback(feedbackEventId: string): Promise<RecommendFeedbackAckVO> {
  if (isMockMode()) {
    return {
      feedback_id: `reversal-${feedbackEventId}`,
      accepted: true,
      feedback_type: 'reversal',
      accepted_count: 1,
      duplicate: false,
      application_status: 'APPLIED',
      preference_version: 2,
    };
  }
  return postJson<RecommendFeedbackAckVO>('/recommend/feedback/reversal', {
    feedback_event_id: feedbackEventId,
  });
}

export async function getFeedbackStatus(feedbackEventId: string): Promise<RecommendFeedbackAckVO> {
  if (isMockMode()) {
    return {
      feedback_id: feedbackEventId,
      accepted: true,
      feedback_type: 'status',
      accepted_count: 0,
      duplicate: false,
      application_status: 'APPLIED',
      preference_version: 1,
    };
  }
  return getJson<RecommendFeedbackAckVO>(`/recommend/feedback/status/${encodeURIComponent(feedbackEventId)}`);
}

export async function waitForFeedbackApplied(
  feedbackEventId: string,
  attempts = 5,
  delayMs = 1000,
): Promise<RecommendFeedbackAckVO> {
  const session = captureAuthSession();
  let status = await getFeedbackStatus(feedbackEventId);
  assertCurrentAuthSession(session);
  for (let attempt = 1; status.application_status === 'PENDING' && attempt < attempts; attempt += 1) {
    await new Promise(resolve => window.setTimeout(resolve, delayMs));
    assertCurrentAuthSession(session);
    status = await getFeedbackStatus(feedbackEventId);
    assertCurrentAuthSession(session);
  }
  return status;
}

export async function getPreferences(): Promise<RecommendPreferencesVO> {
  if (isMockMode()) return { preference_version: 0, items: [] };
  return getJson<RecommendPreferencesVO>('/recommend/preferences');
}

export async function deletePreference(itemId: string): Promise<RecommendFeedbackAckVO> {
  return requestJson<RecommendFeedbackAckVO>('DELETE', `/recommend/preferences/items/${encodeURIComponent(itemId)}`);
}

export async function removePreferenceCompletely(itemId: string): Promise<void> {
  const session = captureAuthSession();
  for (let batch = 0; batch < 20; batch += 1) {
    assertCurrentAuthSession(session);
    const ack = await deletePreference(itemId);
    assertCurrentAuthSession(session);
    if (!ack.accepted) throw new Error('偏好修改未被接受，请刷新后重试。');
    if (ack.application_status === 'PENDING') {
      const status = await waitForFeedbackApplied(ack.feedback_id);
      assertCurrentAuthSession(session);
      if (status.application_status !== 'APPLIED') throw new Error('修改已保存，在线偏好正在同步，请稍后刷新。');
    }
    // APPLIED 仅证明本次反馈投影完成；整个商品历史可能还有待删除的偏好。
    const preferences = await getPreferences();
    assertCurrentAuthSession(session);
    if (!preferences.items.some(item => item.item_id === itemId)) return;
  }
  throw new Error('商品偏好尚未全部删除，请刷新后继续删除。');
}

export async function clearPreferences(): Promise<RecommendPreferenceClearVO> {
  return requestJson<RecommendPreferenceClearVO>('DELETE', '/recommend/preferences');
}

export async function clearPreferencesCompletely(): Promise<void> {
  const session = captureAuthSession();
  let previousState = '';
  let stalledBatches = 0;
  while (stalledBatches < 20) {
    assertCurrentAuthSession(session);
    const result = await clearPreferences();
    assertCurrentAuthSession(session);
    for (const operation of result.operations) {
      if (!operation.accepted) throw new Error('部分偏好修改未被接受，请刷新后重试。');
      if (operation.application_status === 'PENDING') {
        const status = await waitForFeedbackApplied(operation.feedback_id);
        assertCurrentAuthSession(session);
        if (!status.accepted || status.application_status !== 'APPLIED') throw new Error('清空操作已保存，在线偏好正在同步，请稍后继续清空。');
      }
    }
    // 回执与列表都完成后再报告成功，避免将单次投影完成误认为全部清空。
    const current = await getPreferences();
    assertCurrentAuthSession(session);
    if (current.items.length === 0) return;
    const state = JSON.stringify([current.preference_version, current.items.map(item => [item.item_id, item.feedback_event_id, item.preference_version])]);
    stalledBatches = state === previousState ? stalledBatches + 1 : 1;
    previousState = state;
  }
  throw new Error('部分历史偏好尚未清空，请刷新后继续清空。');
}
