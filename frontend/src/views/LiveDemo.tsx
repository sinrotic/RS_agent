import { useState, useEffect } from 'react';
import { mockData } from '../mockData';
import { sendChat, sendFeedback, startSession, fetchSessionExport, runDemoRoundtrip } from '../api';
import { ChatMessage, DisplayResponse, SessionExportResponse, SanitizedTimelineEvent } from '../types';
import { ChatPanel } from '../components/ChatPanel';
import { ReplayPanel } from '../components/ReplayPanel';
import { Brain, Cpu, Sparkles, CheckCircle2, AlertTriangle, Trophy, Star, History, Play } from 'lucide-react';

function parseUserMessage(userMessage: string) {
  let actionType = 'chat';
  let itemId = '';
  let comment = userMessage;

  if (userMessage.includes("I like this item")) {
    actionType = 'like';
  } else if (userMessage.includes("I don't like this item")) {
    actionType = 'dislike';
  } else if (userMessage.includes("show me something different")) {
    actionType = 'show_different';
  } else if (userMessage.includes("why?")) {
    actionType = 'why';
  }

  const match = userMessage.match(/item_id=(\S+)/);
  if (match) {
    itemId = match[1];
  }

  if (actionType !== 'chat') {
    let clean = userMessage;
    if (actionType === 'like') clean = clean.replace("I like this item, show me more like this.", "");
    else if (actionType === 'dislike') clean = clean.replace("I don't like this item, try a different direction.", "");
    else if (actionType === 'show_different') clean = clean.replace("show me something different", "");
    else if (actionType === 'why') clean = clean.replace("why?", "");

    if (itemId) {
      clean = clean.replace(`item_id=${itemId}`, "");
    }
    comment = clean.trim();
  }

  let actionLabel = '发送需求';
  if (actionType === 'like') actionLabel = '商品点赞 (LIKE)';
  else if (actionType === 'dislike') actionLabel = '商品踩/不喜欢 (DISLIKE)';
  else if (actionType === 'show_different') actionLabel = '换一批 (SHOW_DIFFERENT)';
  else if (actionType === 'why') actionLabel = '追问推荐原因 (WHY)';

  return { actionType, itemId, comment, actionLabel };
}

export function LiveDemo() {
  const [sessionId, setSessionId] = useState('');
  const [display, setDisplay] = useState<DisplayResponse>(mockData);
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: 'system', content: '启动后会连接本地 RS Agent 服务；如果后端未启动，会先展示 mock 商品卡。' },
    {
      role: 'assistant',
      content: mockData.assistant_message,
      items: mockData.items,
      thoughts: {
        turn_index: mockData.turn_index,
        conversation_intent: "recommend_request",
        agent_action: "recommend_items",
        tool_calls: [
          { tool_name: "get_user_context", status: "ok", phase: "pre_recommendation" },
          { tool_name: "retrieve_candidates", status: "ok", phase: "pre_recommendation", reason: "Found 100 candidate items from UserCF & Swing paths" },
          { tool_name: "rank_candidates", status: "ok", phase: "pre_recommendation", reason: "DeepFM ranked 100 items, selected top 5" }
        ],
        stop_check: { passed: true, violations: [] },
        rag: { query: "Bluetooth headphones", retriever_name: "sqlite_bm25" }
      }
    }
  ]);
  const [input, setInput] = useState('For commute, prefer bluetooth and Audio');
  const [isLoading, setIsLoading] = useState(false);
  const [status, setStatus] = useState('使用 mock 展示；等待连接后端服务。');
  const [replayData, setReplayData] = useState<SessionExportResponse | null>(null);
  const [replayLoading, setReplayLoading] = useState(false);
  const [replayError, setReplayError] = useState('');
  const [demoLoading, setDemoLoading] = useState(false);

  // New states for 3-column layout
  const [selectedTurnIndex, setSelectedTurnIndex] = useState<number | null>(mockData.turn_index);
  const [likedItems, setLikedItems] = useState<string[]>([]);
  const [dislikedItems, setDislikedItems] = useState<string[]>([]);
  const [timelineEvents, setTimelineEvents] = useState<SanitizedTimelineEvent[]>([
    {
      public_event_id: 'mock-event-1',
      event_type: 'chat',
      turn_index: mockData.turn_index,
      user_message: 'For commute, prefer bluetooth and Audio',
      assistant_message: mockData.assistant_message,
      display_response_index: 0
    }
  ]);

  useEffect(() => {
    let cancelled = false;
    startSession()
      .then((response) => {
        if (cancelled) return;
        setSessionId(response.session_id);
        setDisplay((current) => ({ ...current, session_id: response.session_id }));
        setStatus('已连接本地 RS Agent 服务，可以发送推荐需求。');
        setLikedItems([]);
        setDislikedItems([]);
        setSelectedTurnIndex(null);
        setTimelineEvents([]);
        setMessages([
          { role: 'system', content: '已连接本地 RS Agent 服务，可以发送推荐需求。' }
        ]);
      })
      .catch((error: Error) => {
        if (cancelled) return;
        setStatus(`后端服务未连接：${error.message}。请先启动 scripts/serving/run_service.py，并刷新页面。`);
      });
    return () => { cancelled = true; };
  }, []);

  async function syncSessionHistory(id: string, currentDisplay: DisplayResponse) {
    try {
      const exportData = await fetchSessionExport(id);
      setTimelineEvents(exportData.public_timeline.events);
      const historyMessages: ChatMessage[] = [
        { role: 'system', content: '已连接本地 RS Agent 服务，可以发送推荐需求。' }
      ];
      
      exportData.public_timeline.events.forEach((event) => {
        const turnIndex = event.turn_index;
        const displayResponse = exportData.display_responses[event.display_response_index];
        const thoughts = exportData.agent_thoughts?.find(t => t.turn_index === turnIndex);
        
        if (event.event_type === 'chat' || event.event_type === 'feedback') {
          historyMessages.push({
            role: 'user',
            content: event.user_message,
            thoughts: { turn_index: turnIndex }
          });
        }
        historyMessages.push({
          role: 'assistant',
          content: event.assistant_message,
          items: displayResponse?.items || [],
          thoughts: thoughts
        });
      });
      
      setMessages(historyMessages);
    } catch (e) {
      setMessages((current) => [
        ...current,
        {
          role: 'assistant',
          content: currentDisplay.assistant_message,
          items: currentDisplay.items || []
        }
      ]);
    }
  }

  function handleRequestError(error: unknown) {
    const messageText = error instanceof Error ? error.message : 'Unknown request error';
    if (messageText.includes('Unknown session_id')) {
      setSessionId('');
      setStatus('会话已失效：后端服务可能重启过。请刷新页面重新创建 session。');
      setMessages((current) => [...current, { role: 'system', content: '会话已失效，请刷新页面重新连接后端服务。' }]);
    } else {
      setStatus(`请求失败：${messageText}`);
      setMessages((current) => [...current, { role: 'system', content: `请求失败：${messageText}` }]);
    }
  }

  async function submitMessage(message: string) {
    const trimmed = message.trim();
    if (!trimmed || !sessionId || isLoading) return;
    setIsLoading(true);
    setInput('');
    setMessages((current) => [...current, { role: 'user', content: trimmed }]);
    try {
      const response = await sendChat(sessionId, trimmed);
      setDisplay(response.display);
      setStatus(`Turn ${response.display.turn_index} 已更新。`);
      await syncSessionHistory(sessionId, response.display);
      setSelectedTurnIndex(response.display.turn_index);
    } catch (error) {
      handleRequestError(error);
    } finally {
      setIsLoading(false);
    }
  }

  async function submitFeedback(actionType: string, label: string, itemId?: string) {
    if (!sessionId || isLoading) return;
    setIsLoading(true);
    const target = itemId ? ` on ${itemId}` : '';
    setMessages((current) => [...current, { role: 'user', content: `[Action Submitted]: ${label}${target}` }]);
    
    // Track likes/dislikes
    if (itemId) {
      if (actionType === 'like') {
        setLikedItems(prev => Array.from(new Set([...prev, itemId])));
        setDislikedItems(prev => prev.filter(id => id !== itemId));
      } else if (actionType === 'dislike') {
        setDislikedItems(prev => Array.from(new Set([...prev, itemId])));
        setLikedItems(prev => prev.filter(id => id !== itemId));
      }
    }

    try {
      const response = await sendFeedback(sessionId, actionType, itemId);
      setDisplay(response.display);
      setStatus(`Turn ${response.display.turn_index} 已更新。`);
      await syncSessionHistory(sessionId, response.display);
      setSelectedTurnIndex(response.display.turn_index);
    } catch (error) {
      handleRequestError(error);
    } finally {
      setIsLoading(false);
    }
  }

  async function handleDemoRoundtrip() {
    if (demoLoading || isLoading) return;
    const message = input.trim() || 'For commute, prefer bluetooth and Audio';
    setDemoLoading(true);
    setReplayData(null);
    try {
      const response = await runDemoRoundtrip({ message, feedback_action: 'show_different' });
      setSessionId(response.session_id);
      setDisplay(response.feedback_display);
      const added = response.change_summary.added_item_ids.length;
      const removed = response.change_summary.removed_item_ids.length;
      setStatus(`一键闭环完成：新增 ${added} 个商品，移除 ${removed} 个商品。`);
      await syncSessionHistory(response.session_id, response.feedback_display);
      setSelectedTurnIndex(response.feedback_display.turn_index);
      setLikedItems([]);
      setDislikedItems([]);
    } catch (error) {
      handleRequestError(error);
    } finally {
      setDemoLoading(false);
    }
  }

  async function handleReplay() {
    if (!sessionId || replayLoading) return;
    setReplayLoading(true);
    setReplayError('');
    try {
      const data = await fetchSessionExport(sessionId);
      setReplayData(data);
    } catch (error) {
      const messageText = error instanceof Error ? error.message : 'Unknown request error';
      setReplayError(`Failed to load replay: ${messageText}`);
      setReplayData(null);
    } finally {
      setReplayLoading(false);
    }
  }

  return (
    <div className="xl:h-full flex flex-col min-h-0 xl:overflow-hidden">
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-4 xl:gap-6 items-stretch xl:h-full min-h-0">
        {/* Left Column (xl:col-span-3): Recommender Thoughts Panel */}
        <div className="xl:col-span-3 bg-white rounded-xl shadow-sm border border-gray-200 p-4 h-[550px] xl:h-full flex flex-col gap-3 overflow-hidden">
          <div className="flex items-center gap-2 border-b border-gray-150 pb-2.5 flex-shrink-0">
            <Cpu className="text-indigo-600" size={18} />
            <h2 className="font-bold text-gray-900 text-sm">推荐系统内部思考</h2>
          </div>

          <div className="flex-grow overflow-y-auto pr-1 text-xs font-mono space-y-3 min-h-0 text-left">
            {!selectedTurnIndex ? (
              <div className="h-full flex flex-col items-center justify-center text-gray-400 gap-2 text-center p-4">
                <Brain size={32} className="opacity-30 text-indigo-600" />
                <span className="text-xs">等待交互启动...</span>
                <p className="text-[10px] text-gray-400 leading-normal">发送推荐需求或点击反馈按钮后，点击对话气泡可在此查看该轮次推荐决策的详细轨迹。</p>
              </div>
            ) : (() => {
              const msg = messages.find(m => m.role === 'assistant' && m.thoughts?.turn_index === selectedTurnIndex);
              const thoughts = msg?.thoughts;
              if (!thoughts) {
                return (
                  <div className="h-full flex items-center justify-center text-gray-450 text-center">
                    <span>第 {selectedTurnIndex} 轮暂无推荐决策数据。</span>
                  </div>
                );
              }
              return (
                <div className="space-y-4">
                  <div className="flex justify-between items-center bg-indigo-50 border border-indigo-100 p-2 rounded-lg flex-shrink-0 font-sans">
                    <span className="font-bold text-indigo-850">推荐系统 (第 {selectedTurnIndex} 轮)</span>
                  </div>
                  
                  {/* Intent & Action */}
                  <div className="space-y-1">
                    <div className="font-bold text-gray-800 flex items-center gap-1 font-sans">
                      <Sparkles size={12} className="text-yellow-500" />
                      意图与动作规划
                    </div>
                    <div className="bg-gray-50 border border-gray-150 p-2 rounded space-y-1">
                      <div><span className="text-gray-400 font-sans">用户意图:</span> <span className="text-gray-800 font-bold">{thoughts.conversation_intent || 'N/A'}</span></div>
                      <div><span className="text-gray-400 font-sans">规划动作:</span> <span className="text-gray-800 font-bold">{thoughts.agent_action || 'N/A'}</span></div>
                    </div>
                  </div>

                  {/* Tools trace */}
                  {thoughts.tool_calls && thoughts.tool_calls.length > 0 && (
                    <div className="space-y-1.5">
                      <div className="font-bold text-gray-800 font-sans">工具执行链路:</div>
                      <div className="space-y-1 bg-white border border-gray-155 p-2 rounded">
                        {thoughts.tool_calls.map((tool: any, tIdx: number) => (
                          <div key={tIdx} className="flex justify-between items-center text-[10px]">
                            <span className="text-indigo-600">{tool.tool_name}</span>
                            <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${tool.status === 'ok' ? 'bg-emerald-100 text-emerald-800' : 'bg-red-100 text-red-800'}`}>
                              {tool.status}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* RAG search log */}
                  {thoughts.rag && (
                    <div className="space-y-1">
                      <div className="font-bold text-gray-800 font-sans">RAG 事实检索依据:</div>
                      <div className="bg-white border border-gray-155 p-2 rounded text-[10px]">
                        <div><span className="text-gray-400 font-sans">检索词:</span> "{thoughts.rag.query}"</div>
                        <div><span className="text-gray-400 font-sans">检索方式:</span> {thoughts.rag.retriever_name}</div>
                      </div>
                    </div>
                  )}

                  {/* Stop-check */}
                  {thoughts.stop_check && (
                    <div className="space-y-1">
                      <div className="font-bold text-gray-800 font-sans flex items-center gap-1">
                        {thoughts.stop_check.passed ? (
                          <CheckCircle2 size={12} className="text-emerald-500" />
                        ) : (
                          <AlertTriangle size={12} className="text-amber-500" />
                        )}
                        安全硬拦截校验:
                      </div>
                      <div className="bg-white border border-gray-155 p-2 rounded text-[10px]">
                        <div><span className="text-gray-400 font-sans">安全红线:</span> {thoughts.stop_check.passed ? 'PASSED (符合约束)' : 'REPAIRED (已物理拦截违规推荐)'}</div>
                        {thoughts.stop_check.violations && thoughts.stop_check.violations.length > 0 && (
                          <div className="text-rose-600 mt-1 font-sans font-semibold">
                            已过滤拦截 ASIN: {thoughts.stop_check.violations.map((v: any) => v.parent_asin).join(', ')}
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Rewards */}
                  {thoughts.reward && (
                    <div className="space-y-1">
                      <div className="font-bold text-gray-800 font-sans flex items-center gap-1">
                        <Trophy size={12} className="text-amber-500" />
                        对齐评估反馈奖赏:
                      </div>
                      <div className="bg-white border border-gray-155 p-2 rounded text-[10px] grid grid-cols-2 gap-1.5 font-sans">
                        <div><span className="text-gray-400 font-normal">总得分:</span> <span className="font-bold text-indigo-650">{thoughts.reward.total}</span></div>
                        <div><span className="text-gray-400 font-normal">推荐质量:</span> <span className="text-gray-700">{thoughts.reward.recommendation_quality}</span></div>
                        <div><span className="text-gray-400 font-normal">约束对齐:</span> <span className="text-gray-700">{thoughts.reward.feedback_alignment}</span></div>
                        <div><span className="text-gray-400 font-normal">事实置信:</span> <span className="text-gray-700">{thoughts.reward.explanation_faithfulness}</span></div>
                      </div>
                    </div>
                  )}
                </div>
              );
            })()}
          </div>
        </div>

        {/* Middle Column (xl:col-span-6): ChatPanel */}
        <div className="xl:col-span-6 h-[650px] xl:h-full flex flex-col min-h-0">
          <ChatPanel
            display={display}
            messages={messages}
            input={input}
            setInput={setInput}
            isLoading={isLoading}
            sessionId={sessionId}
            selectedTurnIndex={selectedTurnIndex}
            setSelectedTurnIndex={setSelectedTurnIndex}
            onSubmit={submitMessage}
            onFeedback={submitFeedback}
          />
        </div>

        {/* Right Column (xl:col-span-3): Session details, controls, feedback list, and user trace */}
        <div className="xl:col-span-3 flex flex-col gap-4 h-[650px] xl:h-full overflow-hidden">
          {/* Controls & Session Panel */}
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4 flex flex-col gap-3 flex-shrink-0 text-left">
            <h2 className="font-bold text-gray-900 text-sm border-b border-gray-100 pb-2">会话控制与状态</h2>
            <div className="space-y-2 text-xs text-gray-650">
              <div>
                <span className="text-gray-400 block">当前 Session ID:</span>
                <span className="font-mono text-[10px] font-bold text-gray-800 break-all">{sessionId || '未连接'}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-gray-400 font-medium">当前对话轮数:</span>
                <span className="font-bold text-gray-800">{display.turn_index}</span>
              </div>
              <div>
                <span className="text-gray-400 block font-medium">连接状态:</span>
                <p className="text-[11px] leading-tight mt-0.5 text-gray-600">{status}</p>
              </div>
            </div>

            <div className="flex flex-col gap-2 pt-2 border-t border-gray-100 flex-shrink-0">
              <button
                type="button"
                onClick={handleDemoRoundtrip}
                disabled={demoLoading || isLoading}
                className="w-full flex items-center justify-center gap-2 rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                <Play size={14} />
                {demoLoading ? '运行中...' : '一键闭环演示'}
              </button>
              <button
                type="button"
                onClick={handleReplay}
                disabled={!sessionId || replayLoading || isLoading}
                className="w-full flex items-center justify-center gap-2 rounded-lg bg-gray-100 px-3 py-2 text-xs font-semibold text-gray-700 hover:bg-gray-200 border border-gray-300 disabled:opacity-50"
              >
                <History size={14} />
                {replayLoading ? '加载中...' : '重放当前会话'}
              </button>
            </div>
          </div>

          {/* User Feedback History (Dedicated Panel) */}
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4 flex-grow flex flex-col gap-2 min-h-0 overflow-hidden text-left">
            <div className="flex items-center gap-2 border-b border-gray-100 pb-2 flex-shrink-0">
              <Star className="text-amber-500 fill-amber-500" size={16} />
              <h2 className="font-bold text-gray-900 text-sm">用户反馈历史</h2>
            </div>
            
            <div className="flex-grow overflow-y-auto pr-1 space-y-3 min-h-0 text-xs">
              <div>
                <span className="font-bold text-emerald-700 block mb-1">已点赞商品 (Likes):</span>
                {likedItems.length === 0 ? (
                  <span className="text-gray-400 italic text-[11px]">暂无点赞商品</span>
                ) : (
                  <div className="flex flex-wrap gap-1 mt-1">
                    {likedItems.map(item => (
                      <span key={item} className="bg-emerald-50 border border-emerald-200 text-emerald-800 px-2 py-0.5 rounded font-mono text-[10px]">
                        {item}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              <div>
                <span className="font-bold text-rose-700 block mb-1">已踩/不喜欢商品 (Dislikes):</span>
                {dislikedItems.length === 0 ? (
                  <span className="text-gray-400 italic text-[11px]">暂无不喜欢商品</span>
                ) : (
                  <div className="flex flex-wrap gap-1 mt-1">
                    {dislikedItems.map(item => (
                      <span key={item} className="bg-rose-50 border border-rose-200 text-rose-800 px-2 py-0.5 rounded font-mono text-[10px]">
                        {item}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* User Trace & Feedback Card (Dedicated White Box) */}
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4 h-[200px] flex flex-col gap-2 flex-shrink-0 overflow-hidden text-left">
            <div className="flex items-center gap-2 border-b border-gray-150 pb-2 flex-shrink-0">
              <Brain className="text-purple-600" size={16} />
              <h2 className="font-bold text-gray-900 text-sm">用户决策与反馈轨迹</h2>
            </div>
            
            <div className="flex-grow overflow-y-auto pr-1 text-xs font-mono space-y-2 min-h-0">
              {!selectedTurnIndex ? (
                <div className="h-full flex flex-col items-center justify-center text-gray-400 gap-1 text-center p-2 font-sans">
                  <span>等待交互启动...</span>
                </div>
              ) : (() => {
                const event = timelineEvents.find(e => e.turn_index === selectedTurnIndex);
                if (!event) {
                  return <p className="text-gray-450 italic font-sans text-center mt-4">此轮无具体用户反馈数据。</p>;
                }
                const parsed = parseUserMessage(event.user_message);
                return (
                  <div className="space-y-1.5">
                    <div className="flex justify-between items-center bg-purple-50 border border-purple-100 p-2 rounded-lg flex-shrink-0 font-sans mb-1">
                      <span className="font-bold text-purple-800">用户行为 (第 {selectedTurnIndex} 轮)</span>
                    </div>
                    <div>
                      <span className="text-gray-400 font-sans">决策动作:</span>{' '}
                      <span className="font-bold text-purple-700 uppercase bg-purple-50 px-1 py-0.5 rounded">
                        {parsed.actionLabel}
                      </span>
                    </div>
                    {parsed.itemId && (
                      <div>
                        <span className="text-gray-400 font-sans">目标商品 ASIN:</span>{' '}
                        <span className="font-bold text-gray-800">{parsed.itemId}</span>
                      </div>
                    )}
                    {parsed.comment && (
                      <div>
                        <span className="text-gray-400 font-sans">反馈内容:</span>{' '}
                        <p className="italic text-gray-600 mt-0.5 whitespace-pre-wrap leading-normal font-sans">"{parsed.comment}"</p>
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>
          </div>
        </div>
      </div>

      <ReplayPanel
        data={replayData}
        error={replayError}
        onClose={() => setReplayData(null)}
      />
    </div>
  );
}

