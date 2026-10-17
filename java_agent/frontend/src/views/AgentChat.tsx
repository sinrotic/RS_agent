import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Send, Cpu, User, MessageSquare, Compass, Sparkles } from 'lucide-react';
import { streamChat, fetchAgentHistory, interruptAgent, AgentStreamError } from '../api/agentClient';
import { A2uiView } from '../components/A2uiView';
import { UiState, applyA2uiMessages, uiStateContext, visibleUiProductIds } from '../utils/a2ui';
import { projectAgentUi } from '../utils/agentUiProjection';
import { startSession, listSessions, getSession } from '../api/sessionClient';
import { recordEvent, waitForFeedbackApplied } from '../api/interactionClient';
import { AgentAnswerBlock, ChatMessage } from '../types/agent';
import { RecommendItemVO } from '../types/recommend';
import { DisplayProduct } from '../utils/displayViewModel';
import type { ProductFeedbackAction } from '../components/ProductCard';
import { getStoredProfileUserId, isMockMode, ApiError, createRequestId, captureAuthSession, isCurrentAuthSession } from '../api/shared';
import { UserSession } from '../types/session';
import { hydrateRecommendedProducts } from '../api/catalogHydration';
import { useVisibleRecommendationExposure } from '../hooks/useVisibleRecommendationExposure';

interface AgentChatProps {
  onOpenProduct: (product: DisplayProduct) => void;
}

export function AgentChat({ onOpenProduct }: AgentChatProps) {
  const [profileUserId, setProfileUserId] = useState<string>('');
  const [sessionId, setSessionId] = useState<string>('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);
  const [status, setStatus] = useState<string>('Chat service ready');
  const [activeItems, setActiveItems] = useState<DisplayProduct[]>([]);
  const [lastRequestId, setLastRequestId] = useState<string>('');
  const [lastRecommendedItems, setLastRecommendedItems] = useState<RecommendItemVO[]>([]);
  const [catalogUnavailable, setCatalogUnavailable] = useState<boolean>(false);
  const [degradationReasons, setDegradationReasons] = useState<string[]>([]);
  const [selectedTurnIndex, setSelectedTurnIndex] = useState<number | null>(null);
  const [uiState, setUiState] = useState<UiState>(new Map());
  const uiStateRef = useRef<UiState>(new Map());
  const [displayBlocks, setDisplayBlocks] = useState<AgentAnswerBlock[]>([]);
  const [uiError, setUiError] = useState<string>('');
  const [sessions, setSessions] = useState<UserSession[]>([]);
  const [readOnly, setReadOnly] = useState(false);
  const [resumeFailed, setResumeFailed] = useState(false);
  const [failedMessage, setFailedMessage] = useState<{ message: string; turnId: string; retryable: boolean; feedbackSaved: boolean } | null>(null);
  const activeStream = useRef<{ controller: AbortController; requestId: string; stopped: boolean } | null>(null);
  const mounted = useRef(true);

  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const exposureRootRef = useRef<HTMLDivElement>(null);
  const initializeStartedRef = useRef(false);

  const displayUiState = useMemo(() => projectAgentUi(uiState, {
    products: activeItems, answerBlocks: uiError ? displayBlocks.filter(block => block.type !== 'a2ui') : displayBlocks,
    cardSetId: lastRequestId,
  }), [uiState, activeItems, displayBlocks, lastRequestId, uiError]);
  const visibleUiItems = visibleUiProductIds(displayUiState);
  const uiExposureSignature = visibleUiItems.join(',');
  const exposureRefresh = useMemo(() => ({ activeItems, uiExposureSignature }), [activeItems, uiExposureSignature]);
  useVisibleRecommendationExposure(exposureRootRef, lastRequestId, sessionId, exposureRefresh);

  useEffect(() => {
    mounted.current = true;
    const authSession = captureAuthSession();
    const cleanup = () => {
      mounted.current = false;
      const stream = activeStream.current;
      if (stream?.requestId && isCurrentAuthSession(authSession)) void interruptAgent(stream.requestId).catch(() => undefined);
      stream?.controller.abort();
    };
    if (initializeStartedRef.current) return cleanup;
    initializeStartedRef.current = true;
    const stored = getStoredProfileUserId() || 'guest_user';
    setProfileUserId(stored);
    handleInitChat(stored);
    return cleanup;
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleInitChat = async (userId: string) => {
    setLoading(true);
    setStatus('正在建立对话会话...');
    try {
      setResumeFailed(false);
      const saved = localStorage.getItem(sessionStorageKey(userId));
      if (saved && !isMockMode()) {
        try {
          await restoreSession(saved, userId);
          return;
        } catch (error) {
          if (!(error instanceof ApiError) || error.status !== 404) throw error;
          localStorage.removeItem(sessionStorageKey(userId));
        }
      }
      const sessionRes = await startSession(userId, 'agent_chat');
      if (!mounted.current) return;
      setSessionId(sessionRes.sessionId);
      setReadOnly(false);
      localStorage.setItem(sessionStorageKey(userId), sessionRes.sessionId);
      
      const welcome: ChatMessage = {
        role: 'assistant',
        content: `您好！我是您的推荐智能体(Agent)。我可以通过多轮对话深入理解您的消费需求，并结合推荐算法为您匹配商品。
        
例如，您可以尝试输入：
- *"我想要买一款降噪好、适合坐地铁通勤戴的无线耳机"*
- *"我想买一部复古风格的拍立得相机送给朋友当生日礼物"*
        
请输入您的需求：`,
      };
      setMessages([welcome]);
      setStatus('会话连接成功！');
      await refreshSessions();
    } catch (e: any) {
      setResumeFailed(true);
      setStatus(`初始化对话失败: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  const sessionStorageKey = (userId: string) => `rs_chat_session:${isMockMode() ? 'mock' : 'real'}:${userId}`;

  const refreshSessions = async () => {
    try { const values = await listSessions(); if (mounted.current) setSessions(values); }
    catch { /* History listing failure does not invalidate the active Session. */ }
  };

  const restoreSession = async (id: string, userId: string) => {
    const session = await getSession(id);
    let history;
    try { history = await fetchAgentHistory(id); }
    catch (error) {
      if (!(error instanceof ApiError) || error.status !== 404) throw error;
      history = { session_id: id, turns: [] };
    }
    if (!mounted.current) return;
    setSessionId(id);
    setFailedMessage(null);
    setDegradationReasons([]);
    setReadOnly(session.status !== 'ACTIVE');
    localStorage.setItem(sessionStorageKey(userId), id);
    setMessages(history.turns.flatMap(turn => [
      { role: 'user' as const, content: turn.user_message },
      { role: 'assistant' as const, content: turn.assistant_message || (turn.finish_reason === 'INTERRUPTED' ? '本轮已停止。' : '本轮已完成。'), turnIndex: turn.turn_index },
    ]));
    let restoredUi: UiState = new Map();
    setUiError('');
    for (const turn of history.turns) {
      for (const block of turn.answer_blocks || []) {
        if (block.type !== 'a2ui') continue;
        try { restoredUi = applyA2uiMessages(restoredUi, block.messages || []); }
        catch { setUiError('部分历史界面无法恢复，文字对话仍可查看。'); }
      }
    }
    changeUiState(restoredUi);
    const last = history.turns[history.turns.length - 1];
    setDisplayBlocks(last?.answer_blocks || []);
    setDegradationReasons(last?.degradation_reasons || []);
    const items: RecommendItemVO[] = (last?.recommended_item_ids || []).map((item_id, index) => ({
      item_id, rank: index + 1, score: 0, reason: '历史推荐', source_tags: [],
      display: { title: '', category: '', store: '', image_url: '' },
    }));
    const hydration = await hydrateRecommendedProducts(items);
    if (!mounted.current) return;
    setLastRecommendedItems(items);
    setActiveItems(hydration.products);
    setCatalogUnavailable(hydration.catalogUnavailable);
    setLastRequestId(last?.card_set_id || '');
    setSelectedTurnIndex(last?.turn_index ?? null);
    setStatus(session.status === 'ACTIVE' ? '历史对话已恢复，可以继续。' : '会话已结束，可以查看历史或新建对话。');
    await refreshSessions();
  };

  const switchSession = async (id: string) => {
    if (loading) return;
    setLoading(true);
    try { await restoreSession(id, profileUserId); setResumeFailed(false); }
    catch (error) { setStatus(error instanceof Error ? error.message : '无法恢复会话'); }
    finally { setLoading(false); }
  };

  const newSession = async () => {
    if (loading) return;
    localStorage.removeItem(sessionStorageKey(profileUserId));
    setFailedMessage(null);
    setDegradationReasons([]);
    setCatalogUnavailable(false);
    setActiveItems([]); setLastRecommendedItems([]); setLastRequestId(''); setSelectedTurnIndex(null);
    changeUiState(new Map()); setUiError('');
    setDisplayBlocks([]);
    await handleInitChat(profileUserId);
  };

  const changeUiState = (state: UiState) => {
    uiStateRef.current = state;
    setUiState(state);
  };

  const requestChat = async (message: string, turnId = createRequestId()) => {
    const beforeTurn = uiStateRef.current;
    const beforeDisplayBlocks = displayBlocks;
    const current = { controller: new AbortController(), requestId: '', stopped: false };
    activeStream.current = current;
    try { const response = await streamChat(sessionId, profileUserId, message, block => {
    if (!mounted.current || current.stopped) return;
    if (block.type !== 'a2ui') return;
    try {
      changeUiState(applyA2uiMessages(uiStateRef.current, block.messages || []));
      setDisplayBlocks([block]);
      setUiError('');
    } catch {
      setUiError('交互界面暂时无法显示，您可以继续使用文字对话。');
    }
  }, { a2ui_state: uiStateContext(uiStateRef.current), client_turn_id: turnId }, {
    signal: current.controller.signal,
    onStarted: requestId => {
      current.requestId = requestId;
      if (current.stopped) void stopGeneration();
    },
  });
      if (mounted.current) {
        setDisplayBlocks(response.answerBlocks || []);
        let completedUi = beforeTurn;
        try {
          for (const block of response.answerBlocks || []) {
            if (block.type === 'a2ui') completedUi = applyA2uiMessages(completedUi, block.messages || []);
          }
          changeUiState(completedUi);
          setUiError('');
        } catch { setUiError('交互界面暂时无法显示，您可以继续使用文字对话。'); }
        setDegradationReasons(response.degradationReasons || []);
      }
      return response;
    } catch (error) {
      if (mounted.current) { changeUiState(beforeTurn); setDisplayBlocks(beforeDisplayBlocks); }
      throw error;
    } finally { if (activeStream.current === current) activeStream.current = null; }
  };

  const stopGeneration = async () => {
    const current = activeStream.current;
    if (!current) return;
    current.stopped = true;
    if (!current.requestId) { setStatus('正在等待服务受理后停止生成...'); return; }
    try {
      const interrupted = await interruptAgent(current.requestId);
      if (interrupted) { current.controller.abort(); setStatus('生成已停止。'); }
      else { current.stopped = false; setStatus('本轮正在完成，等待最终结果。'); }
    } catch { current.stopped = false; setStatus('停止请求未确认，请重试。'); }
  };

  const executeMessage = async (message: string, retryTurnId?: string, feedbackSaved = false) => {
    const userMsg = message.trim();
    const turnId = retryTurnId || createRequestId();
    setFailedMessage(null);
    setInput('');
    setLoading(true);
    setStatus('Agent 正在整合特征进行归因与召回编排...');

    // 1. Append user message
    if (!retryTurnId) setMessages(prev => [...prev, { role: 'user', content: userMsg }]);

    try {
      // 2. Request chat response
      const chatRes = await requestChat(userMsg, turnId);
      setLastRequestId(chatRes.cardSetId);
      setLastRecommendedItems(chatRes.items);
      
      // 3. Load catalog details for items
      const hydration = await hydrateRecommendedProducts(chatRes.items);
      const mergedProducts = hydration.products;
      setActiveItems(mergedProducts);
      setDisplayBlocks(chatRes.answerBlocks || []);
      setCatalogUnavailable(hydration.catalogUnavailable);

      // 4. Append assistant response
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: chatRes.assistantMessage,
        items: chatRes.items,
        turnIndex: chatRes.turnIndex,
      }]);

      setSelectedTurnIndex(chatRes.turnIndex);

      setStatus(hydration.catalogUnavailable ? '推荐已更新，商品详情暂不可用。' : '推荐已更新！');

    } catch (e: any) {
      if (e.name === 'AbortError' || e.name === 'AgentInterruptedError') { setStatus(`${feedbackSaved ? '反馈已保存，' : ''}生成已停止，可以继续对话。`); return; }
      const retryable = !(e instanceof ApiError) || e.status >= 500 || e.status === 429;
      setFailedMessage({ message: userMsg, turnId, retryable, feedbackSaved });
      if (e instanceof AgentStreamError && (e.code === 'SESSION_ENDED' || e.code === 'SESSION_NOT_FOUND')) {
        setReadOnly(true); setStatus(`${feedbackSaved ? '反馈已保存，' : ''}${e.message}`); return;
      }
      setStatus(`${feedbackSaved ? '反馈已保存，' : ''}${e instanceof ApiError && e.status === 409
        ? '本轮尚无确认结果，请刷新历史核对后再发起新消息。'
        : '本轮结果未确认，可以重试原消息或刷新历史。'}`);
    } finally {
      setLoading(false);
    }
  };

  const submitMessage = async (message: string, retryTurnId?: string, feedbackSaved = false) => {
    if (!message.trim() || !sessionId || loading || readOnly) return;
    await executeMessage(message, retryTurnId, feedbackSaved);
  };

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    await submitMessage(input);
  };

  const handleFeedback = async (actionType: ProductFeedbackAction, itemId: string) => {
    if (!sessionId || loading || readOnly) return;
    if (!lastRequestId) {
      setStatus('服务端尚未返回 request_id，无法提交反馈。');
      return;
    }
    setLoading(true);
    const label = actionType === 'like' ? '喜欢，找相似' : actionType === 'why' ? '查看推荐理由' : '不感兴趣';
    setStatus(`交互服务正在记录 [${label}] 事件...`);
    let feedbackSaved = false;

    try {
      // 1. Record event
      let ack = await recordEvent({
        request_id: lastRequestId,
        session_id: sessionId,
        item_id: itemId,
        event_type: actionType,
        event_value: actionType === 'why' ? 0 : actionType === 'like' ? 1 : -1,
        occurred_at: Date.now()
      });
      if (!ack.accepted) throw new Error('推荐服务拒绝了本次反馈');
      feedbackSaved = true;

      if (actionType === 'why') {
        const item = activeItems.find(product => product.itemId === itemId);
        setStatus(item?.reason || '当前没有可用的推荐解释。');
        return;
      }

      if (ack.application_status === 'PENDING') {
        setStatus('反馈已保存，在线偏好正在同步...');
        ack = await waitForFeedbackApplied(ack.feedback_id);
        if (ack.application_status !== 'APPLIED') {
          setStatus('反馈已保存，在线偏好仍在同步。');
          return;
        }
      }
      if (ack.application_status !== 'APPLIED') {
        setStatus('反馈已保存，在线偏好尚未确认同步，请稍后刷新偏好。');
        return;
      }

      // 2. Chat with agent that user liked/disliked the item
      const actionMessage = actionType === 'like' 
        ? `我喜欢 ASIN 编号为 ${itemId} 的这款商品，请为我匹配更多具有类似特征的产品。`
        : `我对 ASIN 编号为 ${itemId} 的这款商品不感兴趣，请排除或尝试别的推荐方向。`;
      
      // Generation has its own stable turn ID; retry never resubmits the applied feedback.
      await executeMessage(actionMessage, undefined, true);
    } catch (e: any) {
      setStatus(feedbackSaved ? '反馈已保存，在线偏好同步状态暂时无法确认，请稍后刷新偏好。' : `反馈未确认: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleCatalogRetry = async () => {
    if (loading || lastRecommendedItems.length === 0) return;
    setLoading(true);
    try {
      const hydration = await hydrateRecommendedProducts(lastRecommendedItems);
      setActiveItems(hydration.products);
      setCatalogUnavailable(hydration.catalogUnavailable);
      setStatus(hydration.catalogUnavailable ? '商品详情服务仍不可用。' : '商品详情重新加载成功。');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div ref={exposureRootRef} className="flex-1 flex flex-col gap-6 text-slate-100 overflow-hidden min-h-[75vh]">
      {/* Top Banner */}
      <div className="relative rounded-2xl bg-linear-to-r from-purple-600 via-indigo-900 to-slate-950 p-6 shadow-lg overflow-hidden shrink-0 text-left">
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

      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label className="text-slate-300">历史对话
          <select aria-label="历史对话" value={sessions.some(value => value.sessionId === sessionId) ? sessionId : ''}
            onChange={event => { if (event.target.value) void switchSession(event.target.value); }} disabled={loading}
            className="ml-2 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2">
            <option value="">当前对话</option>
            {sessions.map(value => <option key={value.sessionId} value={value.sessionId}>
              {new Date(value.startedAt).toLocaleString('zh-CN')} · {value.status === 'ACTIVE' ? '可继续' : '已结束'}
            </option>)}
          </select>
        </label>
        <button type="button" disabled={loading} onClick={() => void newSession()} className="rounded-lg border border-indigo-500/40 px-3 py-2">新建对话</button>
        {resumeFailed && <button type="button" disabled={loading} onClick={() => void handleInitChat(profileUserId)} className="rounded-lg border border-amber-400/40 px-3 py-2">重试连接</button>}
        {failedMessage && <>
          {failedMessage.retryable && <button type="button" disabled={loading} onClick={() => void submitMessage(failedMessage.message, failedMessage.turnId, failedMessage.feedbackSaved)} className="rounded-lg border border-amber-400/40 px-3 py-2">重试原消息</button>}
          <button type="button" disabled={loading} onClick={() => void switchSession(sessionId)} className="rounded-lg border border-slate-600 px-3 py-2">刷新历史</button>
        </>}
      </div>
      {/* Grid Content */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-5 gap-6 min-h-0">
        {/* Chat History Panel */}
        <div className="lg:col-span-3 flex flex-col bg-slate-800/60 border border-slate-700/60 rounded-2xl overflow-hidden glass-panel min-h-[400px]">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-slate-700/50 p-4 shrink-0">
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
                    className={`rounded-2xl p-3.5 text-xs leading-relaxed shadow-xs font-medium whitespace-pre-wrap ${
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
          <form onSubmit={handleSend} className="p-4 border-t border-slate-700/50 bg-slate-900/20 flex gap-2 shrink-0">
            <input
              type="text"
              value={input}
              onChange={e => setInput(e.target.value)}
              disabled={loading || !sessionId || readOnly}
              placeholder="输入您的细化购买需求或调整指令..."
              className="grow min-w-0 rounded-xl bg-slate-950/60 border border-slate-700/60 focus:border-indigo-500 focus:outline-hidden focus:ring-2 focus:ring-indigo-500/20 px-4 py-3 text-xs text-white placeholder-slate-650"
            />
            <button
              type="submit"
              disabled={loading || !sessionId || !input.trim() || readOnly}
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
            {loading && activeStream.current && <button type="button" onClick={() => void stopGeneration()}
              className="rounded-xl border border-rose-400/40 px-4 text-xs text-rose-200">停止生成</button>}
          </form>
        </div>

        {/* Association recommended items */}
        <div className="lg:col-span-2 flex flex-col bg-slate-800/60 border border-slate-700/60 rounded-2xl overflow-hidden glass-panel min-h-[400px]">
          {/* Header */}
          <div className="border-b border-slate-700/50 p-4 text-left flex items-center justify-between shrink-0">
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
            {uiError && <p role="status" className="text-xs text-amber-200">{uiError}</p>}
            {degradationReasons.length > 0 && <p role="status" className="rounded border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-200">
              {degradationReasons.includes('recommendation_unavailable')
                ? '推荐服务暂时不可用，您可以继续描述需求，稍后再获取商品推荐。'
                : '个性化排序暂时不可用，当前展示基础推荐结果，您仍可继续对话和调整偏好。'}
            </p>}
            <A2uiView state={displayUiState} products={activeItems} disabled={loading || readOnly}
              feedbackDisabled={!lastRequestId}
              onStateChange={state => changeUiState(new Map(Array.from(uiStateRef.current,
                ([id, surface]) => [id, { ...surface, data: state.has(id) ? state.get(id)!.data : surface.data }] as const)))}
              onSubmit={query => { void submitMessage(query); }}
              onFeedback={handleFeedback}
              onOpen={product => onOpenProduct({ ...product, sessionId, recommendRequestId: lastRequestId })} />
            {catalogUnavailable && (
              <div role="status" className="flex items-center justify-between gap-2 border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
                <span>商品详情暂时无法加载，正在展示 Agent 推荐结果。</span>
                <button type="button" onClick={handleCatalogRetry} disabled={loading} className="rounded border border-amber-400/40 px-2 py-1 hover:bg-amber-400/10 disabled:opacity-50">
                  重试
                </button>
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
