import {
  AgentRunMonitorVO,
  PlatformSessionOverviewVO,
  PlatformTimelineEventVO,
  RecommendTraceVO
} from '../types/platformTrace';
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

export function mockAgentRunMonitor(sessionId: string, requestId?: string): AgentRunMonitorVO {
  const resolvedSessionId = sessionId || 'mock-session';
  const resolvedRequestId = requestId || 'agent_req_mock_001';
  const now = Date.now();

  return {
    session_id: resolvedSessionId,
    request_id: resolvedRequestId,
    status: 'success',
    summary: {
      total_latency_ms: 2480,
      prompt_tokens: 1260,
      completion_tokens: 420,
      total_tokens: 1680,
      model_provider: 'openai',
      model_name: 'gpt-4.1-mini',
      tool_call_count: 2,
      error_count: 0,
      recommend_item_count: 4,
      has_final_answer: true
    },
    phases: [
      {
        phase: 'intent',
        status: 'success',
        event_count: 1,
        latency_ms: 420,
        total_tokens: 360
      },
      {
        phase: 'tool',
        status: 'success',
        event_count: 2,
        latency_ms: 1160,
        total_tokens: 540
      },
      {
        phase: 'answer',
        status: 'success',
        event_count: 1,
        latency_ms: 900,
        total_tokens: 780
      }
    ],
    events: [
      {
        event_id: 'agent_evt_mock_001',
        session_id: resolvedSessionId,
        request_id: resolvedRequestId,
        event_type: 'llm_response',
        phase: 'intent',
        status: 'success',
        tool_call_id: '',
        tool_name: '',
        agent_name: 'shopping_agent',
        model_provider: 'openai',
        model_name: 'gpt-4.1-mini',
        latency_ms: 420,
        prompt_tokens: 260,
        completion_tokens: 100,
        total_tokens: 360,
        error_code: '',
        error_message: '',
        input_summary: 'User asked for commuting product recommendations.',
        output_summary: 'Detected portable audio and electronics intent.',
        data: { intent: 'commuting_audio' },
        created_at: new Date(now - 3000).toISOString()
      },
      {
        event_id: 'agent_evt_mock_002',
        session_id: resolvedSessionId,
        request_id: resolvedRequestId,
        event_type: 'tool_call',
        phase: 'tool',
        status: 'success',
        tool_call_id: 'call_mock_001',
        tool_name: 'recommend_candidates',
        agent_name: 'shopping_agent',
        model_provider: 'openai',
        model_name: 'gpt-4.1-mini',
        latency_ms: 720,
        prompt_tokens: 420,
        completion_tokens: 120,
        total_tokens: 540,
        error_code: '',
        error_message: '',
        input_summary: 'Fetch candidate items for commuting audio intent.',
        output_summary: 'Retrieved ranked candidate set.',
        data: { candidate_count: 24 },
        created_at: new Date(now - 2200).toISOString()
      },
      {
        event_id: 'agent_evt_mock_003',
        session_id: resolvedSessionId,
        request_id: resolvedRequestId,
        event_type: 'tool_result',
        phase: 'tool',
        status: 'success',
        tool_call_id: 'call_mock_001',
        tool_name: 'recommend_candidates',
        agent_name: 'shopping_agent',
        model_provider: 'openai',
        model_name: 'gpt-4.1-mini',
        latency_ms: 440,
        prompt_tokens: 0,
        completion_tokens: 0,
        total_tokens: 0,
        error_code: '',
        error_message: '',
        input_summary: 'Rank candidate products.',
        output_summary: 'Selected top recommendations with reason tags.',
        data: {
          item_ids: MOCK_RECOMMEND_ITEMS.slice(0, 4).map((item) => item.item_id)
        },
        created_at: new Date(now - 1500).toISOString()
      },
      {
        event_id: 'agent_evt_mock_004',
        session_id: resolvedSessionId,
        request_id: resolvedRequestId,
        event_type: 'llm_response',
        phase: 'answer',
        status: 'success',
        tool_call_id: '',
        tool_name: '',
        agent_name: 'shopping_agent',
        model_provider: 'openai',
        model_name: 'gpt-4.1-mini',
        latency_ms: 900,
        prompt_tokens: 580,
        completion_tokens: 200,
        total_tokens: 780,
        error_code: '',
        error_message: '',
        input_summary: 'Summarize recommendations and tradeoffs.',
        output_summary: 'Generated final answer with four product recommendations.',
        data: { final_answer: true },
        created_at: new Date(now - 600).toISOString()
      }
    ],
    quality_signals: ['final_answer_present', 'tool_trace_complete', 'recommendations_linked'],
    related_traces: {
      agent_turn_count: 1,
      recommend_request_ids: ['mock-rec-req'],
      interaction_event_count: 2
    }
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

export async function getAgentRequestMonitor(requestId: string): Promise<AgentRunMonitorVO> {
  if (isMockMode()) {
    await mockDelay(250);
    return mockAgentRunMonitor('mock-session', requestId);
  }
  return getJson<AgentRunMonitorVO>(`/platform/agent/runs/${encodeURIComponent(requestId)}/monitor`);
}

export async function getAgentSessionMonitor(sessionId: string, requestId?: string): Promise<AgentRunMonitorVO> {
  if (isMockMode()) {
    await mockDelay(250);
    return mockAgentRunMonitor(sessionId, requestId);
  }

  const params = new URLSearchParams();
  if (requestId) params.set('request_id', requestId);
  const suffix = params.toString() ? `?${params.toString()}` : '';
  return getJson<AgentRunMonitorVO>(`/platform/sessions/${encodeURIComponent(sessionId)}/agent-monitor${suffix}`);
}
