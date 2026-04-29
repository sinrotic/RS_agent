import { FormEvent, useEffect, useRef, useState } from 'react';
import { mockData } from './mockData';
import { Image as ImageIcon, MessageSquare, Send, ThumbsUp, ThumbsDown, RefreshCw, HelpCircle, History, Play } from 'lucide-react';
import { sendChat, sendFeedback, startSession, fetchSessionExport, runSimulationScene, runDemoRoundtrip } from './api';
import { ChatMessage, DisplayItem, DisplayResponse, FeedbackAction, SessionExportResponse, SimulationSceneResponse } from './types';

function ProductCard({ item, onFeedback, disabled }: { item: DisplayItem; onFeedback: (actionType: string, itemId: string) => void; disabled: boolean }) {
  const [imgError, setImgError] = useState(false);
  const price = typeof item.price === 'number' ? `$${item.price.toFixed(2)}` : item.price;

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden flex flex-col h-full transition-shadow hover:shadow-md">
      <div className="h-48 bg-gray-100 flex items-center justify-center relative border-b border-gray-200">
        {item.image_url && !imgError ? (
          <img
            src={item.image_url}
            alt={item.title || item.parent_asin}
            className="w-full h-full object-contain"
            onError={() => setImgError(true)}
          />
        ) : (
          <div className="flex flex-col items-center justify-center text-gray-400">
            <ImageIcon size={48} className="mb-2 opacity-50" />
            <span className="text-sm font-medium">No Image Available</span>
          </div>
        )}
        <div className="absolute top-2 right-2 flex flex-col gap-1">
          {item.badges.map((badge) => (
            <span key={badge} className="bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full opacity-90 shadow-sm whitespace-nowrap">
              {badge.replace(/_/g, ' ')}
            </span>
          ))}
        </div>
      </div>
      <div className="p-4 flex flex-col flex-grow">
        {item.category && <div className="text-xs text-gray-500 mb-1">{item.category}</div>}
        <h3 className="font-semibold text-lg leading-tight mb-2 flex-grow">
          {item.title || `Item ${item.parent_asin}`}
        </h3>
        {price && <div className="font-bold text-gray-900 mb-2">{price}</div>}
        {item.summary && <p className="text-sm text-gray-600 mb-4 line-clamp-2">{item.summary}</p>}
        {item.description && <p className="text-sm text-gray-500 mb-4 line-clamp-3">{item.description}</p>}
        {item.features.length > 0 && (
          <ul className="text-xs text-gray-500 list-disc list-inside mb-4">
            {item.features.slice(0, 3).map((feature) => (
              <li key={feature} className="truncate">{feature}</li>
            ))}
          </ul>
        )}
        <div className="mt-auto space-y-3">
          <div className="flex justify-between items-center text-xs text-gray-500">
            <span>ASIN: {item.parent_asin}</span>
            {item.rating && <span>⭐ {item.rating}</span>}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => onFeedback('like', item.parent_asin)}
              disabled={disabled}
              className="rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1.5 text-xs font-semibold text-emerald-700 hover:bg-emerald-100 disabled:opacity-50"
            >
              喜欢
            </button>
            <button
              type="button"
              onClick={() => onFeedback('dislike', item.parent_asin)}
              disabled={disabled}
              className="rounded-md border border-rose-200 bg-rose-50 px-2 py-1.5 text-xs font-semibold text-rose-700 hover:bg-rose-100 disabled:opacity-50"
            >
              不喜欢
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function actionIcon(type: string) {
  switch (type) {
    case 'like': return <ThumbsUp size={16} />;
    case 'dislike': return <ThumbsDown size={16} />;
    case 'show_different': return <RefreshCw size={16} />;
    case 'why': return <HelpCircle size={16} />;
    default: return <MessageSquare size={16} />;
  }
}

export default function App() {
  const [sessionId, setSessionId] = useState('');
  const [display, setDisplay] = useState<DisplayResponse>(mockData);
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: 'system', content: '启动后会连接本地 RS Agent 服务；如果后端未启动，会先展示 mock 商品卡。' },
  ]);
  const [input, setInput] = useState('For commute, prefer bluetooth and Audio');
  const [isLoading, setIsLoading] = useState(false);
  const [status, setStatus] = useState('使用 mock 展示；等待连接后端服务。');
  const [replayData, setReplayData] = useState<SessionExportResponse | null>(null);
  const [replayLoading, setReplayLoading] = useState(false);
  const [replayError, setReplayError] = useState('');
  
  const [simLoading, setSimLoading] = useState(false);
  const [simError, setSimError] = useState('');
  const [simScene, setSimScene] = useState<SimulationSceneResponse | null>(null);
  const [simRole, setSimRole] = useState('commuter_practical');
  const [simMaxTurns, setSimMaxTurns] = useState(4);
  const [demoLoading, setDemoLoading] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  async function handleRunSimulation() {
    setSimLoading(true);
    setSimError('');
    setSimScene(null);
    try {
      const response = await runSimulationScene({ role_id: simRole, max_turns: simMaxTurns });
      setSimScene(response);
    } catch (error) {
      setSimError(error instanceof Error ? error.message : 'Unknown error');
    } finally {
      setSimLoading(false);
    }
  }

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  async function handleDemoRoundtrip() {
    if (demoLoading || isLoading) return;
    const message = input.trim() || 'For commute, prefer bluetooth and Audio';
    setDemoLoading(true);
    setReplayData(null);
    try {
      const response = await runDemoRoundtrip({ message, feedback_action: 'show_different' });
      setSessionId(response.session_id);
      setDisplay(response.feedback_display);
      setMessages([
        { role: 'user', content: message },
        { role: 'assistant', content: response.first_display.assistant_message },
        { role: 'user', content: '[Action Submitted]: 换一批' },
        { role: 'assistant', content: response.feedback_display.assistant_message },
      ]);
      const added = response.change_summary.added_item_ids.length;
      const removed = response.change_summary.removed_item_ids.length;
      setStatus(`一键闭环完成：新增 ${added} 个商品，移除 ${removed} 个商品。`);
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

  useEffect(() => {
    let cancelled = false;
    startSession()
      .then((response) => {
        if (cancelled) return;
        setSessionId(response.session_id);
        setDisplay((current) => ({ ...current, session_id: response.session_id }));
        setStatus('已连接本地 RS Agent 服务，可以发送推荐需求。');
      })
      .catch((error: Error) => {
        if (cancelled) return;
        setStatus(`后端服务未连接：${error.message}。请先启动 scripts/run_service.py，并刷新页面。`);
      });
    return () => { cancelled = true; };
  }, []);

  function applyDisplayUpdate(nextDisplay: DisplayResponse) {
    setDisplay(nextDisplay);
    setMessages((current) => [...current, { role: 'assistant', content: nextDisplay.assistant_message }]);
    setStatus(`Turn ${nextDisplay.turn_index} 已更新。`);
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
      applyDisplayUpdate(response.display);
    } catch (error) {
      handleRequestError(error);
    } finally {
      setIsLoading(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submitMessage(input);
  }

  async function submitFeedback(actionType: string, label: string, itemId?: string) {
    if (!sessionId || isLoading) return;
    setIsLoading(true);
    const target = itemId ? ` on ${itemId}` : '';
    setMessages((current) => [...current, { role: 'user', content: `[Action Submitted]: ${label}${target}` }]);
    try {
      const response = await sendFeedback(sessionId, actionType, itemId);
      applyDisplayUpdate(response.display);
    } catch (error) {
      handleRequestError(error);
    } finally {
      setIsLoading(false);
    }
  }

  async function handleAction(action: FeedbackAction) {
    await submitFeedback(action.type, action.label);
  }

  function handleItemFeedback(actionType: string, itemId: string) {
    const label = actionType === 'like' ? '喜欢该商品' : '不喜欢该商品';
    void submitFeedback(actionType, label, itemId);
  }

  return (
    <div className="min-h-screen bg-gray-50 py-8 px-4 sm:px-6 lg:px-8">
      <div className="max-w-6xl mx-auto space-y-8">
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 flex flex-col gap-4">
          <div className="flex items-start gap-4">
            <div className="bg-indigo-100 p-3 rounded-full flex-shrink-0">
              <MessageSquare className="text-indigo-600" size={24} />
            </div>
            <div className="flex-1">
              <div className="flex justify-between items-start gap-4">
                <div>
                  <h1 className="text-xl font-bold text-gray-900 mb-1">RS Agent Frontend Demo</h1>
                  <p className="text-gray-700">{display.assistant_message}</p>
                </div>
                <div className="flex flex-wrap justify-end gap-2">
                  <button
                    type="button"
                    onClick={handleDemoRoundtrip}
                    disabled={demoLoading || isLoading}
                    className="flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 whitespace-nowrap"
                  >
                    <Play size={16} />
                    {demoLoading ? 'Running...' : '一键闭环'}
                  </button>
                  <button
                    type="button"
                    onClick={handleReplay}
                    disabled={!sessionId || replayLoading || isLoading}
                    className="flex items-center gap-2 rounded-lg bg-gray-100 px-4 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-200 border border-gray-300 disabled:opacity-50 whitespace-nowrap"
                  >
                    <History size={16} />
                    {replayLoading ? 'Loading...' : 'Replay Session'}
                  </button>
                </div>
              </div>
              <div className="mt-2 text-xs text-gray-400 flex flex-wrap gap-4">
                <span>Session: {display.session_id}</span>
                <span>Turn: {display.turn_index}</span>
                <span>{status}</span>
              </div>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="flex flex-col sm:flex-row gap-3">
            <input
              value={input}
              onChange={(event) => setInput(event.target.value)}
              disabled={!sessionId || isLoading}
              className="flex-1 rounded-lg border border-gray-300 px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:bg-gray-100"
              placeholder="输入推荐需求，例如：I want headphones for commute"
            />
            <button
              type="submit"
              disabled={!sessionId || isLoading || !input.trim()}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-indigo-600 px-5 py-3 text-sm font-semibold text-white hover:bg-indigo-700 disabled:bg-gray-300"
            >
              <Send size={16} />
              {isLoading ? '发送中' : '发送'}
            </button>
          </form>

          <div className="rounded-lg bg-gray-50 border border-gray-200 p-3 space-y-2 max-h-44 overflow-y-auto">
            {messages.map((message, index) => (
              <div key={`${message.role}-${index}`} className="text-sm">
                <span className="font-semibold text-gray-700">{message.role}: </span>
                <span className="text-gray-600">{message.content}</span>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>
        </div>

        <div>
          <h2 className="text-lg font-semibold text-gray-800 mb-4 px-1">Recommendations</h2>
          {display.items.length > 0 ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
              {display.items.map((item) => (
                <ProductCard key={item.parent_asin} item={item} onFeedback={handleItemFeedback} disabled={!sessionId || isLoading} />
              ))}
            </div>
          ) : (
            <div className="bg-white rounded-lg border border-dashed border-gray-300 p-8 text-center text-gray-500">
              这一轮是澄清或解释回复，没有新的商品卡。
            </div>
          )}
        </div>

        <div className="flex flex-wrap gap-3 justify-center pt-4">
          {display.feedback_actions.map((action) => (
            <button
              key={action.type}
              onClick={() => handleAction(action)}
              disabled={!sessionId || isLoading}
              className="flex items-center gap-2 px-4 py-2 bg-white border border-gray-300 rounded-full shadow-sm hover:bg-gray-50 hover:border-gray-400 transition-colors text-sm font-medium text-gray-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 disabled:opacity-50"
            >
              {actionIcon(action.type)}
              {action.label}
            </button>
          ))}
        </div>

        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 flex flex-col gap-4 mt-8">
          <div className="flex items-center justify-between border-b border-gray-100 pb-4">
            <h2 className="text-xl font-bold text-gray-900 flex items-center gap-2">
              <Play size={20} className="text-indigo-600" />
              Simulation Scene
            </h2>
          </div>
          <div className="flex flex-wrap gap-4 items-end">
            <div className="flex flex-col gap-1">
              <label className="text-sm font-medium text-gray-700">Role Preset</label>
              <select 
                value={simRole} 
                onChange={e => setSimRole(e.target.value)}
                className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-indigo-500 focus:border-indigo-500 bg-white"
                disabled={simLoading}
              >
                <option value="commuter_practical">Commuter Practical</option>
                <option value="gift_buyer">Gift Buyer</option>
                <option value="price_sensitive">Price Sensitive</option>
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-sm font-medium text-gray-700">Max Turns</label>
              <input 
                type="number" 
                min="1" 
                max="10" 
                value={simMaxTurns}
                onChange={e => setSimMaxTurns(parseInt(e.target.value))}
                className="border border-gray-300 rounded-lg px-3 py-2 text-sm w-24 focus:ring-indigo-500 focus:border-indigo-500"
                disabled={simLoading}
              />
            </div>
            <button
              onClick={handleRunSimulation}
              disabled={simLoading}
              className="rounded-lg bg-indigo-600 px-5 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:bg-gray-300 whitespace-nowrap h-10 flex items-center gap-2"
            >
              {simLoading && <RefreshCw size={16} className="animate-spin" />}
              {simLoading ? 'Running...' : 'Run Simulation'}
            </button>
          </div>

          {simError && (
            <div className="bg-red-50 border border-red-200 text-red-600 rounded-lg p-4 text-sm mt-2">
              {simError}
            </div>
          )}

          {simScene && (
            <div className="mt-4 flex flex-col gap-6">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 text-sm">
                  <h3 className="font-bold text-blue-900 mb-2 border-b border-blue-200 pb-2">Role: {simScene.role.role_id}</h3>
                  <div className="space-y-1 text-blue-800">
                    <div><span className="font-semibold">Persona:</span> {simScene.role.persona}</div>
                    <div><span className="font-semibold">Goal:</span> {simScene.role.shopping_goal}</div>
                    <div><span className="font-semibold">Style:</span> {simScene.role.decision_style} / {simScene.role.feedback_style}</div>
                    <div><span className="font-semibold">Categories:</span> {simScene.role.category_preferences.join(', ')}</div>
                    <div><span className="font-semibold">Keywords:</span> {simScene.role.keyword_preferences.join(', ')}</div>
                    <div><span className="font-semibold">Negative:</span> {simScene.role.negative_preferences.join(', ')}</div>
                  </div>
                </div>
                <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-sm">
                  <h3 className="font-bold text-green-900 mb-2 border-b border-green-200 pb-2">Final State</h3>
                  <div className="space-y-1 text-green-800">
                    <div><span className="font-semibold">Satisfaction:</span> {simScene.state.satisfaction} / 5.0</div>
                    <div><span className="font-semibold">Final Action:</span> {simScene.state.final_action}</div>
                    <div><span className="font-semibold">Accepted Item:</span> {simScene.state.accepted_item_id || 'None'}</div>
                    <div><span className="font-semibold">Turns Observed:</span> {simScene.state.turns_observed}</div>
                    <div><span className="font-semibold">Seen Items:</span> {simScene.state.seen_item_ids.length}</div>
                  </div>
                </div>
              </div>

              <div className="bg-white border border-gray-200 rounded-lg p-4">
                <h3 className="font-bold text-gray-900 mb-4 border-b border-gray-100 pb-2">Actions Timeline</h3>
                <div className="space-y-4">
                  {simScene.actions.map((action, i) => (
                    <div key={i} className="flex gap-3 text-sm">
                      <div className="flex flex-col items-center">
                        <div className="w-6 h-6 rounded-full bg-gray-100 border border-gray-300 flex items-center justify-center text-xs font-bold text-gray-600">{action.turn_index}</div>
                        {i < simScene.actions.length - 1 && <div className="w-px h-full bg-gray-200 my-1"></div>}
                      </div>
                      <div className="flex-1 pb-2">
                        <div className="font-semibold text-gray-800 uppercase text-xs tracking-wider mb-1">
                          {action.type} {action.action_type ? `• ${action.action_type}` : ''}
                        </div>
                        {action.message && <div className="text-gray-700 bg-gray-50 p-2 rounded border border-gray-100">"{action.message}"</div>}
                        {action.comment && <div className="text-gray-600 mt-1 italic text-xs">Comment: "{action.comment}"</div>}
                        {action.item_id && <div className="text-gray-500 mt-1 text-xs">Item: {action.item_id}</div>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="bg-white border border-gray-200 rounded-lg p-4">
                <h3 className="font-bold text-gray-900 mb-4 border-b border-gray-100 pb-2">Session Summary</h3>
                <div className="space-y-4">
                  {simScene.session.events.map((event, i) => {
                    const displayInfo = simScene.session.display_responses[event.display_response_index];
                    return (
                      <div key={i} className="border border-indigo-100 rounded-lg bg-indigo-50/30 p-4 text-sm">
                        <div className="flex justify-between items-start mb-2">
                          <span className="text-xs font-semibold text-indigo-800 bg-indigo-100 px-2 py-1 rounded">Turn {event.turn_index} - {event.type.toUpperCase()}</span>
                        </div>
                        <div className="mb-2">
                          <span className="font-semibold text-gray-800">User: </span>
                          <span className="text-gray-700">
                            {event.type === 'chat' ? event.user_input : `Feedback [${event.action_type}]`}
                            {event.item_id && ` on item ${event.item_id}`}
                            {event.comment && ` - "${event.comment}"`}
                          </span>
                        </div>
                        <div className="mb-3">
                          <span className="font-semibold text-indigo-700">Agent: </span>
                          <span className="text-gray-700">{event.assistant_message}</span>
                        </div>
                        {displayInfo?.items && displayInfo.items.length > 0 && (
                          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2 mt-3 pt-3 border-t border-indigo-100">
                            {displayInfo.items.map(item => (
                              <div key={item.parent_asin} className="bg-white border border-gray-200 rounded p-1.5 text-xs">
                                 <div className="font-medium text-gray-800 truncate" title={item.title || item.parent_asin}>{item.title || item.parent_asin}</div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
        </div>

        {replayData && (
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 flex flex-col gap-4 mt-8">
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-bold text-gray-900">Session Replay</h2>
              <button onClick={() => setReplayData(null)} className="text-sm text-gray-500 hover:text-gray-700">Close</button>
            </div>
            {replayData.events.length === 0 ? (
              <div className="text-center text-gray-500 py-4">No events found in this session.</div>
            ) : (
              <div className="space-y-8 mt-4">
                {replayData.events.map((event, i) => {
                  const displayInfo = replayData.display_responses[event.display_response_index];
                  return (
                    <div key={i} className="border border-indigo-100 rounded-lg p-4 bg-indigo-50/30">
                      <div className="flex justify-between items-start mb-3">
                        <span className="text-xs font-semibold text-indigo-800 bg-indigo-100 px-2 py-1 rounded">Turn {event.turn_index} - {event.type.toUpperCase()}</span>
                      </div>
                      
                      <div className="mb-2">
                        <span className="font-semibold text-gray-800">User: </span>
                        <span className="text-gray-700">
                          {event.type === 'chat' ? event.user_input : `Feedback [${event.action_type}]`}
                          {event.item_id && ` on item ${event.item_id}`}
                          {event.comment && ` - "${event.comment}"`}
                        </span>
                      </div>
                      
                      <div className="mb-4">
                        <span className="font-semibold text-indigo-700">Agent: </span>
                        <span className="text-gray-700">{event.assistant_message}</span>
                      </div>
                      
                      {displayInfo?.items && displayInfo.items.length > 0 ? (
                        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3 mt-4 pt-4 border-t border-indigo-100">
                          {displayInfo.items.map(item => (
                            <div key={item.parent_asin} className="bg-white border border-gray-200 rounded-lg p-2 text-xs flex flex-col gap-1">
                               <div className="font-medium text-gray-800 truncate" title={item.title || item.parent_asin}>{item.title || item.parent_asin}</div>
                               {item.price && <div className="text-gray-900 font-semibold">{typeof item.price === 'number' ? `$${item.price.toFixed(2)}` : item.price}</div>}
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="mt-4 pt-4 border-t border-indigo-100 text-xs text-gray-500 italic">
                          No items displayed.
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
        
        {replayError && (
          <div className="bg-red-50 border border-red-200 text-red-600 rounded-lg p-4 mt-8 text-sm">
            {replayError}
          </div>
        )}
      </div>
    </div>
  );
}
