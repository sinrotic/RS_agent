import { AgentAnswerBlock, AgentChatRequest, AgentChatResponse, AgentChatWireResponse, AgentHistory } from '../types/agent';
import { RecommendItemVO } from '../types/recommend';
import { isMockMode, postJson, getJson, postEventStream, mockDelay, ApiError } from './shared';
import { MOCK_RECOMMEND_ITEMS } from './recommendClient';

export class AgentStreamError extends ApiError {
  constructor(status: number, public readonly code: string, public readonly retryable: boolean) {
    super(status === 409 ? '本轮结果需要核对，请刷新历史后发起新消息。'
      : status === 410 ? '会话已结束，请新建对话。'
      : status === 404 ? '会话不存在或不属于当前账号，请新建对话。'
      : 'Agent 对话未完成，请重新发送。', status);
    this.name = 'AgentStreamError';
  }
}

export async function sendChat(
  sessionId: string,
  profileUserId: string,
  message: string,
): Promise<AgentChatResponse> {
  if (isMockMode()) {
    await mockDelay(1200); // AI needs a bit of thinking time

    const msgLower = message.toLowerCase();
    let reply = '';
    let items: RecommendItemVO[] = [];

    if (msgLower.includes('耳机') || msgLower.includes('audio') || msgLower.includes('commute') || msgLower.includes('sound') || msgLower.includes('听')) {
      reply = `我已经为您筛选了最适合通勤和日常听音的无线蓝牙耳机及便携音箱。

我们重点召回了含有 **主动降噪(ANC)** 和 **高清蓝牙传输(LDAC/AptX)** 特性的音频商品，并结合您的画像进行了排序：
1. **Sony WH-1000XM4**：旗舰级主动降噪耳机，为您在地铁和办公室提供绝对的安静。
2. **JBL Flip 6**：便携户外防水设计，适合骑行或户外运动。
3. **Anker Soundcore Life Q30**：极具性价比的主动降噪方案，适合长期通勤备用。

您可以点击右侧商品卡片的“为什么推荐”查看更详细的推荐分数构成。`;
      items = MOCK_RECOMMEND_ITEMS.filter(item => item.display.category.includes('Audio'));
    } else if (msgLower.includes('相机') || msgLower.includes('camera') || msgLower.includes('gift') || msgLower.includes('送礼') || msgLower.includes('记录')) {
      reply = `收到！针对您的“送礼/创意摄制/生活记录”诉求，我为您挑选了以下几款高口碑的数码影像产品：

1. **Fujifilm Instax Mini 11**：复古可爱的拍立得，即拍即得，马卡龙配色，非常适合作为礼物赠送。
2. **Sony Alpha ZV-1**：小巧轻便的 Vlog 创作者微单，对焦极快，带防抖，是日常视频记录的绝对神器。

这些商品结合了数据集内热门赠礼标签，排在您的候选集前列。`;
      items = MOCK_RECOMMEND_ITEMS.filter(item => item.display.category.includes('Camera'));
    } else {
      reply = `您好！我是您的智能推荐助理。我能够理解您的自然语言购物诉求，并在底层调用推荐召回和 ONNX 排序模型为您筛选商品。

例如，您可以尝试输入：
- *"我想要一款性价比高、适合送朋友的复古相机"*
- *"日常地铁通勤，想要头戴式且降噪深度好的蓝牙耳机"*

目前我为您推荐了一组综合评分最高的热门数码与配件商品：`;
      items = MOCK_RECOMMEND_ITEMS;
    }

    return {
      requestId: `agent_req_${Date.now()}_${Math.floor(Math.random() * 1000)}`,
      sessionId,
      profileUserId,
      cardSetId: `mock_card_set_${Date.now()}`,
      turnIndex: 1,
      assistantMessage: reply,
      items,
      toolCalls: [],
    };
  }

  // Real request to Java Endpoint: rs-service-agent -> POST /api/agent/chat
  const request = agentChatRequest(sessionId, profileUserId, message);
  const response = await postJson<AgentChatWireResponse>('/agent/chat', request);
  return mapAgentChatResponse(response);
}

export function agentChatRequest(
  sessionId: string,
  profileUserId: string,
  message: string,
  context: Record<string, unknown> = {},
): AgentChatRequest {
  return {
    session_id: sessionId,
    profile_user_id: profileUserId,
    user_message: message,
    limit: 5,
    context: { ...context, scene: 'agent_chat' },
  };
}

export async function streamChat(
  sessionId: string, profileUserId: string, message: string,
  onBlock: (block: AgentAnswerBlock) => void, context: Record<string, unknown> = {},
  options: { signal?: AbortSignal; onStarted?: (requestId: string) => void } = {},
): Promise<AgentChatResponse> {
  if (isMockMode()) {
    const response = await sendChat(sessionId, profileUserId, message);
    response.answerBlocks?.forEach(onBlock);
    return response;
  }
  let completed: AgentChatResponse | undefined;
  await postEventStream('/agent/chat/stream', agentChatRequest(sessionId, profileUserId, message, context), (event, data) => {
    if (event === 'started' && typeof data.request_id === 'string') options.onStarted?.(data.request_id);
    if (event === 'answer_block') onBlock(data as unknown as AgentAnswerBlock);
    if (event === 'interrupted') {
      const error = new Error('生成已停止。'); error.name = 'AgentInterruptedError'; throw error;
    }
    if (event === 'error') {
      const status = typeof data.status === 'number' ? data.status : 500;
      const codes = ['TURN_CONFLICT', 'SESSION_ENDED', 'SESSION_NOT_FOUND', 'AGENT_BUSY', 'AGENT_STREAM_FAILED'];
      const code = typeof data.error_code === 'string' && codes.includes(data.error_code) ? data.error_code : 'AGENT_STREAM_FAILED';
      throw new AgentStreamError(status, code, status >= 500 || status === 429);
    }
    if (event === 'done') {
      if (!data.response || data.finish_reason === 'error') throw new Error('Agent stream missing completed response');
      completed = mapAgentChatResponse(data.response as AgentChatWireResponse);
    }
  }, options.signal);
  if (!completed) throw new Error('Agent stream ended before completion');
  return completed;
}

export async function fetchAgentHistory(sessionId: string): Promise<AgentHistory> {
  if (isMockMode()) return { session_id: sessionId, turns: [] };
  return getJson<AgentHistory>(`/agent/sessions/${encodeURIComponent(sessionId)}/history`);
}

export async function interruptAgent(requestId: string): Promise<boolean> {
  if (isMockMode()) return true;
  const result = await postJson<{ interrupted: boolean }>(`/agent/requests/${encodeURIComponent(requestId)}/interrupt`, { reason: 'user_stop' });
  return result.interrupted;
}

export function mapAgentChatResponse(response: AgentChatWireResponse): AgentChatResponse {
  if (!response?.request_id) {
    throw new Error('Agent response missing request_id');
  }
  if (!Number.isInteger(response.turn_index)) {
    throw new Error('Agent response missing turn_index');
  }
  if (typeof response.assistant_message !== 'string'
    || (!response.assistant_message && !response.answer_blocks?.length)) {
    throw new Error('Agent response missing assistant_message');
  }
  if (!Array.isArray(response.recommended_items)) {
    throw new Error('Agent response missing recommended_items');
  }
  if (response.recommended_items.length > 0 && !response.card_set_id) {
    throw new Error('Agent response missing card_set_id');
  }
  return {
    requestId: response.request_id,
    sessionId: response.session_id,
    profileUserId: response.profile_user_id,
    cardSetId: response.card_set_id || '',
    turnIndex: response.turn_index,
    assistantMessage: response.assistant_message,
    items: (response.recommended_items || []).map((item, index) => ({
      item_id: item.item_id,
      rank: index + 1,
      score: item.score,
      reason: item.reason || '',
      source_tags: [],
      display: {
        title: item.title || '',
        category: item.category || '',
        store: '',
        image_url: '',
      },
    })),
    toolCalls: response.tool_calls || [],
    degradationReasons: (response.degradation_reasons || []).filter(reason =>
      reason === 'trained_ranking_unavailable' || reason === 'model_rank_unavailable' || reason === 'recommendation_unavailable'),
    ...(response.answer_blocks ? { answerBlocks: response.answer_blocks } : {}),
  };
}
