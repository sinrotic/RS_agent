import { PlatformSessionOverviewVO, PlatformTimelineEventVO, RecommendTraceVO } from '../types/platformTrace';
import { getJson, isMockMode, mockDelay } from './shared';
import { MOCK_RECOMMEND_ITEMS } from './recommendClient';

function mockRecommendTrace(requestId: string, sessionId: string, profileUserId: string): RecommendTraceVO {
  return {
    request_id: requestId || 'mock-rec-req',
    session_id: sessionId || 'mock-session',
    profile_user_id: profileUserId || 'guest_user',
    scene: 'home',
    stage_counts: {
      recall: 500,
      coarse_rank: 100,
      fine_rank: 50,
      final: MOCK_RECOMMEND_ITEMS.length
    },
    source_distribution: {
      collaborative_filtering: 2,
      content_semantic: 2,
      category_hot: 1,
      cold_fallback: 1
    },
    items: MOCK_RECOMMEND_ITEMS.slice(0, 4).map((item) => ({
      item_id: item.item_id,
      final_rank: item.rank,
      final_score: item.score,
      recall_sources: item.source_tags,
      reason: item.reason
    }))
  };
}

export async function getSessionOverview(
  sessionId: string,
  accountId?: string,
  requestId?: string,
  profileUserId?: string
): Promise<PlatformSessionOverviewVO> {
  if (isMockMode()) {
    await mockDelay(300);
    return {
      session_id: sessionId || 'mock-session',
      account_profile: {
        account_id: accountId || 'mock-account',
        profile_user_id: profileUserId || 'guest_user',
        profile_summary: 'Mock profile: recent interest in audio, camera, and portable electronics.',
        top_categories: ['Audio', 'Camera', 'Portable'],
        top_stores: ['Sony Electronics Store', 'JBL Flagship Store']
      },
      agent_trace: {
        session_id: sessionId || 'mock-session',
        turns: [
          {
            request_id: 'agent_req_mock_001',
            user_message: 'Need a commuting product recommendation',
            assistant_message: 'Matched intent to audio and portable electronics.',
            tool_calls: ['recommend_candidates', 'rank_candidates'],
            recommended_item_ids: MOCK_RECOMMEND_ITEMS.slice(0, 3).map((item) => item.item_id)
          }
        ]
      },
      recommend_traces: [mockRecommendTrace(requestId || 'mock-rec-req', sessionId, profileUserId || 'guest_user')],
      interaction_events: [
        {
          event_id: 'interaction_evt_mock_001',
          session_id: sessionId || 'mock-session',
          request_id: requestId || 'mock-rec-req',
          item_id: MOCK_RECOMMEND_ITEMS[0]?.item_id || 'mock-item',
          event_type: 'exposure',
          event_value: 1,
          occurred_at: new Date(Date.now() - 120000).toISOString(),
          metadata: { source: 'mock' }
        },
        {
          event_id: 'interaction_evt_mock_002',
          session_id: sessionId || 'mock-session',
          request_id: requestId || 'mock-rec-req',
          item_id: MOCK_RECOMMEND_ITEMS[0]?.item_id || 'mock-item',
          event_type: 'like',
          event_value: 1,
          occurred_at: new Date(Date.now() - 60000).toISOString(),
          metadata: { source: 'mock' }
        }
      ],
      timeline: [
        {
          event_id: 'agent_evt_mock_001',
          session_id: sessionId || 'mock-session',
          request_id: 'agent_req_mock_001',
          event_type: 'tool_result',
          source: 'agent',
          entity_id: 'call_mock_001',
          summary: 'recommend_candidates',
          occurred_at: new Date(Date.now() - 180000).toISOString(),
          data: { status: 'SUCCESS' }
        },
        {
          event_id: 'interaction_evt_mock_002',
          session_id: sessionId || 'mock-session',
          request_id: requestId || 'mock-rec-req',
          event_type: 'like',
          source: 'interaction',
          entity_id: MOCK_RECOMMEND_ITEMS[0]?.item_id || 'mock-item',
          summary: 'like mock item',
          occurred_at: new Date(Date.now() - 60000).toISOString(),
          data: { event_value: 1 }
        }
      ]
    };
  }

  const params = new URLSearchParams();
  if (accountId) params.set('account_id', accountId);
  if (requestId) params.set('request_id', requestId);
  const suffix = params.toString() ? `?${params.toString()}` : '';
  return getJson<PlatformSessionOverviewVO>(`/platform/sessions/${encodeURIComponent(sessionId)}/overview${suffix}`);
}

export async function getRecommendTrace(requestId: string): Promise<RecommendTraceVO> {
  if (isMockMode()) {
    await mockDelay(250);
    return mockRecommendTrace(requestId, 'mock-session', 'guest_user');
  }
  return getJson<RecommendTraceVO>(`/platform/recommend/${encodeURIComponent(requestId)}/trace`);
}

export async function getSessionTimeline(sessionId: string): Promise<PlatformTimelineEventVO[]> {
  if (isMockMode()) {
    const overview = await getSessionOverview(sessionId);
    return overview.timeline;
  }
  return getJson<PlatformTimelineEventVO[]>(`/platform/sessions/${encodeURIComponent(sessionId)}/timeline`);
}
