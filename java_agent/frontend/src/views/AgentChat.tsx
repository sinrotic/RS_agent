import React, { useState, useEffect, useRef } from 'react';
import { Send, Cpu, User, MessageSquare, Compass, Sparkles, AlertCircle } from 'lucide-react';
import { sendChat, toRecommendItems } from '../api/agentClient';
import { startSession } from '../api/sessionClient';
import { recordEvent, recordExposure } from '../api/interactionClient';
import { ChatMessage } from '../types/agent';
import { DisplayProduct } from '../utils/displayViewModel';
import { ProductCard, ProductFeedbackAction } from '../components/ProductCard';
import { getStoredProfileUserId } from '../api/shared';
import { enrichRecommendedProducts } from '../utils/catalogEnrichment';

export function AgentChat() {
  const [profileUserId, setProfileUserId] = useState<string>('');
  const [sessionId, setSessionId] = useState<string>('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);
  const [status, setStatus] = useState<string>('Chat service ready');
  const [activeItems, setActiveItems] = useState<DisplayProduct[]>([]);
  const [selectedTurnIndex, setSelectedTurnIndex] = useState<number | null>(null);
  const [lastRequestId, setLastRequestId] = useState<string>('');
  const [catalogUnavailable, setCatalogUnavailable] = useState<boolean>(false);

  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const stored = getStoredProfileUserId() || 'guest_user';
    setProfileUserId(stored);
    handleInitChat(stored);
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleInitChat = async (userId: string) => {
    setLoading(true);
    setStatus('正在建立对话会话...');
    try {
      const sessionRes = await startSession(userId);
      setSessionId(sessionRes.sessionId);
      
      const welcome: ChatMessage = {
        role: 'assistant',
        content: `您好！我是您的推荐智能体(Agent)。我可以通过多轮对话深入理解您的消费需求，并结合推荐算法为您匹配商品。
        
例如，您可以尝试输入：
- *"我想要买一款降噪好、适合坐地铁通勤戴的无线耳机"*
- *"我想买一部复古风格的拍立得相机送给朋友当生日礼物"*
        
请输入您的需求：`,
        turnIndex: 0
      };
      setMessages([welcome]);
      setStatus('会话连接成功！');
    } catch (e: any) {
      setStatus(`初始化对话失败: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || !sessionId || loading) return;

    const userMsg = input.trim();
    setInput('');
    setLoading(true);
    setStatus('Agent 正在整合特征进行归因与召回编排...');

    // 1. Append user message
    setMessages(prev => [...prev, { role: 'user', content: userMsg }]);

    try {
      // 2. Request chat response
      const chatRes = await sendChat({
        session_id: sessionId,
        profile_user_id: profileUserId,
        user_message: userMsg,
        limit: 6,
        context: { scene: 'agent_chat' },
      });
      const resolvedRequestId = chatRes.request_id;
      setLastRequestId(resolvedRequestId);
      
      // 3. Reuse the homepage Catalog enrichment and its degraded fallback.
      const recommendationItems = toRecommendItems(chatRes.recommended_items);
      const { products: mergedProducts, catalogAvailable } = await enrichRecommendedProducts(recommendationItems);
      setCatalogUnavailable(!catalogAvailable);
      setActiveItems(mergedProducts);

      // 4. Append assistant response
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: chatRes.assistant_message,
        items: recommendationItems,
        turnIndex: chatRes.turn_index
      }]);

      setSelectedTurnIndex(chatRes.turn_index);
      setStatus(catalogAvailable ? '推荐已更新！' : '推荐已更新，商品详情服务暂时不可用。');

      // 5. Record Exposure
      if (mergedProducts.length > 0) {
        await recordExposure({
          request_id: resolvedRequestId,
          session_id: sessionId,
          item_ids: mergedProducts.map(item => item.itemId),
          exposed_at: Date.now()
        });
      }
    } catch (e: any) {
      setStatus(`对话回复错误: ${e.message}`);
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `抱歉，接口发生错误，无法从推荐底座中召回商品：${e.message}`,
        turnIndex: 99
      }]);
    } finally {
      setLoading(false);
    }
  };

  const handleFeedback = async (actionType: ProductFeedbackAction, itemId: string) => {
    if (!sessionId || loading) return;
    if (!lastRequestId) {
      setStatus('服务端尚未返回 request_id，无法提交反馈。');
      return;
    }
    if (actionType === 'why') {
      try {
        await recordEvent({
          request_id: lastRequestId,
          session_id: sessionId,
          item_id: itemId,
          event_type: 'why',
          occurred_at: Date.now()
        });
      } catch (error) {
        setStatus(`Explanation request failed: ${(error as Error).message}`);
        return;
      }
      const product = activeItems.find(item => item.itemId === itemId);
      setStatus(product?.reason || '推荐服务暂未返回该商品的解释。');
      return;
    }
    setLoading(true);
    const label = actionType === 'like' ? '喜欢，找相似' : '不感兴趣';
    setStatus(`交互服务正在记录 [${label}] 事件...`);

    try {
      // 1. Record event
      await recordEvent({
        request_id: lastRequestId,
        session_id: sessionId,
        item_id: itemId,
        event_type: actionType,
        occurred_at: Date.now()
      });

      // 2. Chat with agent that user liked/disliked the item
      const actionMessage = actionType === 'like' 
        ? `我喜欢 ASIN 编号为 ${itemId} 的这款商品，请为我匹配更多具有类似特征的产品。`
        : `我对 ASIN 编号为 ${itemId} 的这款商品不感兴趣，请排除或尝试别的推荐方向。`;
      
      // Append user instruction
      setMessages(prev => [...prev, { role: 'user', content: actionMessage }]);

      const chatRes = await sendChat({
        session_id: sessionId,
        profile_user_id: profileUserId,
        user_message: actionMessage,
        limit: 6,
        context: { scene: 'agent_chat', feedback_action: actionType, item_id: itemId },
      });
      const resolvedRequestId = chatRes.request_id;
      setLastRequestId(resolvedRequestId);
      const recommendationItems = toRecommendItems(chatRes.recommended_items);
      
      const { products: mergedProducts, catalogAvailable } = await enrichRecommendedProducts(recommendationItems);
      setCatalogUnavailable(!catalogAvailable);
      setActiveItems(mergedProducts);

      setMessages(prev => [...prev, {
        role: 'assistant',
        content: chatRes.assistant_message,
        items: recommendationItems,
        turnIndex: chatRes.turn_index
      }]);

      setSelectedTurnIndex(chatRes.turn_index);
      setStatus(catalogAvailable
        ? '兴趣偏好微调成功，推荐列表已更新。'
        : '兴趣偏好已更新，商品详情服务暂时不可用。');
    } catch (e: any) {
      setStatus(`反馈更新失败: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleCatalogRetry = async () => {
    if (loading || activeItems.length === 0) return;
    setLoading(true);
    try {
      const recommendationItems = activeItems.map((item) => ({
        item_id: item.itemId,
        rank: item.rank,
        score: item.score,
        reason: item.reason,
        source_tags: item.badges,
        display: {
          title: item.title,
          category: item.category,
          store: item.store,
          image_url: item.imageUrl || '',
        },
      }));
      const { products, catalogAvailable } = await enrichRecommendedProducts(recommendationItems);
      setActiveItems(products);
      setCatalogUnavailable(!catalogAvailable);
      setStatus(catalogAvailable ? '商品详情重新加载成功。' : '商品详情服务仍不可用。');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col gap-6 text-slate-100 overflow-hidden min-h-[75vh]">
      {/* Top Banner */}
      <div className="relative rounded-2xl bg-gradient-to-r from-purple-600 via-indigo-900 to-slate-950 p-6 shadow-lg overflow-hidden flex-shrink-0 text-left">
        <div className="absolute inset-0 bg-[linear-gradient(to_right,#80808012_1px,transparent_1px),linear-gradient(to_bottom,#80808012_1px,transparent_1px)] bg-[size:24px_24px] opacity-15"></div>
        <div className="relative z-10 flex items-center justify-between">
          <div className="space-y-1">
            <div className="inline-flex items-center gap-1.5 px-3 py-0.5 bg-white/10 backdrop-blur-md rounded-full text-[10px] font-bold text-purple-300 tracking-wide uppercase">
              <MessageSquare size={12} />
              AI Agent Dialog Interface
            </div>
            <h1 className="text-xl md:text-2xl font-extrabold tracking-tight">智能推荐对话助手</h1>
            <p className="text-slate-400 text-xs">通过大模型理解用户诉求，并将其翻译为召回、排序阶段的过滤标签与排序模型上下文权重。</p>
          </div>
        </div>
      </div>

      {/* Grid Content */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-5 gap-6 min-h-0">
        {/* Chat History Panel */}
        <div className="lg:col-span-3 flex flex-col bg-slate-800/60 border border-slate-700/60 rounded-2xl overflow-hidden glass-panel min-h-[400px]">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-slate-700/50 p-4 flex-shrink-0">
            <div className="flex items-center gap-2">
              <div className="bg-indigo-500/10 p-2 rounded-xl text-indigo-400 border border-indigo-500/20">
                <Compass size={16} />
              </div>
              <div className="text-left">
                <div className="text-xs font-bold text-slate-100">对话上下文流 ({status})</div>
                <div className="text-[10px] text-slate-400">会话ID: {sessionId || '未激活'} · Turn: {selectedTurnIndex ?? '-'}</div>
              </div>
            </div>
            <div className="text-[10px] bg-slate-900 px-2 py-0.5 rounded text-indigo-400 font-bold border border-slate-700">
              User: {profileUserId}
            </div>
          </div>

          {/* Dialogue History */}
          <div className="flex-1 p-4 overflow-y-auto space-y-4 min-h-0 scrollbar-thin">
            {messages.map((msg, index) => {
              const isUser = msg.role === 'user';
              return (
                <div 
                  key={index} 
                  className={`flex flex-col gap-1 max-w-[85%] text-left ${isUser ? 'self-end items-end ml-auto' : 'self-start items-start mr-auto'}`}
                >
                  <div className="text-[9px] text-slate-500 px-1 font-bold uppercase flex items-center gap-1">
                    {isUser ? <User size={9} className="text-purple-400" /> : <Cpu size={9} className="text-indigo-400" />}
                    {isUser ? '您 (USER)' : '智能推荐体 (RECOMMEND AGENT)'}
                  </div>
                  <div 
                    className={`rounded-2xl p-3.5 text-xs leading-relaxed shadow-sm font-medium whitespace-pre-wrap ${
                      isUser 
                        ? 'bg-indigo-600 text-white rounded-tr-none' 
                        : 'bg-slate-900/80 text-slate-100 border border-slate-700/60 rounded-tl-none'
                    }`}
                  >
                    {msg.content}
                  </div>
                </div>
              );
            })}
            <div ref={messagesEndRef} />
          </div>

          {/* Input Form */}
          <form onSubmit={handleSend} className="p-4 border-t border-slate-700/50 bg-slate-900/20 flex gap-2 flex-shrink-0">
            <input
              type="text"
              value={input}
              onChange={e => setInput(e.target.value)}
              disabled={loading || !sessionId}
              placeholder="输入您的细化购买需求或调整指令..."
              className="flex-grow rounded-xl bg-slate-950/60 border border-slate-700/60 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 px-4 py-3 text-xs text-white placeholder-slate-650"
            />
            <button
              type="submit"
              disabled={loading || !sessionId || !input.trim()}
              className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-xl px-5 py-3 text-xs font-bold transition-all shadow-md shadow-indigo-600/25 flex items-center gap-1 cursor-pointer"
            >
              {loading ? (
                <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
              ) : (
                <>
                  <Send size={12} />
                  发送
                </>
              )}
            </button>
          </form>
        </div>

        {/* Association recommended items */}
        <div className="lg:col-span-2 flex flex-col bg-slate-800/60 border border-slate-700/60 rounded-2xl overflow-hidden glass-panel min-h-[400px]">
          {/* Header */}
          <div className="border-b border-slate-700/50 p-4 text-left flex items-center justify-between flex-shrink-0">
            <div className="flex items-center gap-2">
              <div className="bg-purple-500/10 p-2 rounded-xl text-purple-400 border border-purple-500/20 animate-pulse">
                <Sparkles size={16} />
              </div>
              <div>
                <div className="text-xs font-bold text-slate-100 font-sans">关联推荐结果</div>
                <div className="text-[9px] text-slate-400">基于多轮对话意图的召回与重排结果</div>
              </div>
            </div>
            <span className="text-[10px] font-bold bg-indigo-500/10 text-indigo-300 px-2 py-0.5 rounded border border-indigo-500/20">
              {activeItems.length} 个结果
            </span>
          </div>

          {/* Product Items List */}
          <div className="flex-1 p-4 overflow-y-auto space-y-4 scrollbar-thin min-h-0">
            {catalogUnavailable && (
              <div role="status" className="flex items-center justify-between gap-2 border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
                <span>商品详情暂时无法加载，正在展示 Agent 推荐结果。</span>
                <button type="button" onClick={handleCatalogRetry} disabled={loading} className="rounded border border-amber-400/40 px-2 py-1 hover:bg-amber-400/10 disabled:opacity-50">
                  重试
                </button>
              </div>
            )}
            {activeItems.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-24 text-slate-500 gap-2">
                <AlertCircle size={28} className="opacity-40" />
                <div className="text-xs">暂无对话推荐商品，请在左侧发送您的意向诉求。</div>
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-4">
                {activeItems.map((item) => (
                  <ProductCard
                    key={item.itemId}
                    item={item}
                    onFeedback={handleFeedback}
                    disabled={loading}
                    variant="compact"
                  />
                ))}
              </div>
            )}
          </div>

          {/* Footer obs */}
          <div className="p-3 border-t border-slate-700/50 bg-slate-900/40 text-[9px] text-slate-400 text-left">
            💡 <span className="font-bold text-indigo-400">提示</span>：当您点击“喜欢”或“不感兴趣”时，系统将触发一条对话式调整，向 Agent 传达您的倾向偏好并重新进行召回。
          </div>
        </div>
      </div>
    </div>
  );
}
