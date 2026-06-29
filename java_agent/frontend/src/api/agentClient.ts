import { AgentChatResponse } from '../types/agent';
import { RecommendItemVO } from '../types/recommend';
import { isMockMode, postJson, mockDelay } from './shared';
import { MOCK_RECOMMEND_ITEMS } from './recommendClient';

export async function sendChat(sessionId: string, message: string): Promise<AgentChatResponse> {
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
      assistantMessage: reply,
      items,
      turnIndex: Math.floor(Math.random() * 5) + 1,
      evidence: [
        { source: 'RAG Context', query: message, matches: items.length }
      ]
    };
  }

  // Real request to Java Endpoint: rs-service-agent -> POST /api/agent/chat
  return postJson<AgentChatResponse>('/agent/chat', { sessionId, message });
}
