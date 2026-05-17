import { useState, useEffect } from 'react';
import { mockData } from '../mockData';
import { sendChat, sendFeedback, startSession, fetchSessionExport, runDemoRoundtrip } from '../api';
import { ChatMessage, DisplayResponse, SessionExportResponse } from '../types';
import { ChatPanel } from '../components/ChatPanel';
import { ProductGrid } from '../components/ProductGrid';
import { FeedbackActions } from '../components/FeedbackActions';
import { ReplayPanel } from '../components/ReplayPanel';

export function LiveDemo() {
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
  const [demoLoading, setDemoLoading] = useState(false);

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
        setStatus(`后端服务未连接：${error.message}。请先启动 scripts/serving/run_service.py，并刷新页面。`);
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

  return (
    <div className="space-y-8">
      <ChatPanel
        display={display}
        status={status}
        messages={messages}
        input={input}
        setInput={setInput}
        isLoading={isLoading}
        sessionId={sessionId}
        demoLoading={demoLoading}
        replayLoading={replayLoading}
        onDemoRoundtrip={handleDemoRoundtrip}
        onReplay={handleReplay}
        onSubmit={submitMessage}
      />

      <div>
        <h2 className="text-lg font-semibold text-gray-800 mb-4 px-1">Recommendations</h2>
        <ProductGrid
          items={display.items}
          onFeedback={(actionType, itemId) => submitFeedback(actionType, actionType === 'like' ? '喜欢该商品' : '不喜欢该商品', itemId)}
          disabled={!sessionId || isLoading}
        />
      </div>

      <FeedbackActions
        actions={display.feedback_actions}
        onAction={(action) => submitFeedback(action.type, action.label)}
        disabled={!sessionId || isLoading}
      />

      <ReplayPanel
        data={replayData}
        error={replayError}
        onClose={() => setReplayData(null)}
      />
    </div>
  );
}
