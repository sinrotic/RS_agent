import { FormEvent, useEffect, useRef } from 'react';
import { Send, MessageSquare, Cpu, User } from 'lucide-react';
import { ChatMessage, DisplayResponse } from '../types';
import { ProductCard } from './ProductCard';

interface ChatPanelProps {
  display: DisplayResponse;
  messages: ChatMessage[];
  input: string;
  setInput: (value: string) => void;
  isLoading: boolean;
  sessionId: string;
  selectedTurnIndex: number | null;
  setSelectedTurnIndex: (turnIndex: number | null) => void;
  onSubmit: (message: string) => void;
  onFeedback: (actionType: string, label: string, itemId?: string) => void;
}

export function ChatPanel({
  display, messages, input, setInput, isLoading, sessionId,
  selectedTurnIndex, setSelectedTurnIndex,
  onSubmit, onFeedback
}: ChatPanelProps) {
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit(input);
  }

  const isLatestAssistantMessage = (index: number) => {
    for (let i = messages.length - 1; i > index; i--) {
      if (messages[i].role === 'assistant') return false;
    }
    return messages[index].role === 'assistant';
  };

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 flex flex-col gap-4 h-full overflow-hidden">
      {/* Dialogue Header */}
      <div className="flex items-start gap-4 border-b border-gray-100 pb-3 flex-shrink-0">
        <div className="bg-indigo-100 p-2.5 rounded-full flex-shrink-0">
          <MessageSquare className="text-indigo-600" size={20} />
        </div>
        <div className="flex-1 text-left">
          <h1 className="text-lg font-bold text-gray-900 mb-0.5">推荐系统实时演示</h1>
          <p className="text-gray-500 text-xs">通过多维度交互与反馈，实时体验并观察智能推荐系统的交互回放摘要。</p>
        </div>
      </div>

      {/* Messages timeline */}
      <div className="flex-grow rounded-xl bg-gray-50 border border-gray-200 p-4 space-y-4 overflow-y-auto flex flex-col min-h-0">
        {messages.map((message, index) => {
          if (message.role === 'system') {
            return (
              <div key={`msg-${index}`} className="self-center bg-gray-200/60 text-gray-500 rounded-full px-4 py-1 text-xs text-center font-medium my-1 max-w-[90%] flex-shrink-0">
                {message.content}
              </div>
            );
          }

          const isUser = message.role === 'user';
          // Associate turns for both user and assistant messages if available
          const turnIndex = message.thoughts?.turn_index;
          const isSelected = turnIndex !== undefined && turnIndex === selectedTurnIndex;
          const hasTurn = turnIndex !== undefined;

          return (
            <div
              key={`msg-${index}`}
              onClick={() => {
                if (hasTurn) setSelectedTurnIndex(turnIndex);
              }}
              className={`flex flex-col gap-1 max-w-[85%] transition-all duration-200 ${
                isUser ? 'self-end items-end' : 'self-start items-start w-full'
              } ${
                isSelected 
                  ? isUser
                    ? 'scale-[1.01] ring-2 ring-purple-400 ring-offset-2 ring-offset-gray-50 shadow-md rounded-2xl'
                    : 'scale-[1.01] ring-2 ring-indigo-400 ring-offset-2 ring-offset-gray-50 shadow-md rounded-2xl'
                  : hasTurn ? 'cursor-pointer hover:scale-[1.005]' : ''
              }`}
            >
              <div className="text-[10px] text-gray-400 px-2 font-semibold uppercase flex items-center gap-1">
                {isUser ? <User size={10} className="text-purple-500" /> : <Cpu size={10} className="text-indigo-555" />}
                {isUser ? '用户' : '推荐系统'}
              </div>
              <div
                className={`rounded-2xl p-4 text-sm shadow-sm text-left w-full ${
                  isUser
                    ? 'bg-indigo-600 text-white rounded-tr-none'
                    : 'bg-white text-gray-800 border border-gray-200 rounded-tl-none'
                }`}
              >
                <p className="whitespace-pre-wrap leading-relaxed">{message.content}</p>

                {/* Inline Product Grid */}
                {message.items && message.items.length > 0 && (
                  <div className="mt-4 pt-4 border-t border-gray-100">
                    <h4 className="font-semibold text-xs text-gray-505 uppercase tracking-wider mb-3">为您推荐以下商品：</h4>
                    <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
                      {message.items.map((item) => (
                        <div key={item.parent_asin} className="w-full">
                          <ProductCard
                            item={item}
                            onFeedback={(actionType, itemId) => onFeedback(actionType, actionType === 'like' ? '喜欢该商品' : '不喜欢该商品', itemId)}
                            disabled={isLoading || !sessionId}
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Turn Info & outer inspect hint */}
                {isUser && hasTurn && (
                  <div className="mt-2 text-[9px] text-indigo-200 border-t border-indigo-500/30 pt-1.5 flex justify-between items-center">
                    <span>第 {turnIndex} 轮需求</span>
                    <span className="text-indigo-100 font-semibold">点击查看交互摘要</span>
                  </div>
                )}

                {!isUser && message.thoughts && (
                  <div className="mt-3 text-[9px] text-gray-400 border-t border-gray-150 pt-1.5 flex justify-between items-center">
                    <span>第 {message.thoughts.turn_index} 轮推荐</span>
                    <span className="text-indigo-600 font-semibold">点击查看推荐依据摘要</span>
                  </div>
                )}
              </div>

              {/* Inline Feedback Quick Reply Chips (Only for the latest Assistant message) */}
              {!isUser && isLatestAssistantMessage(index) && display.feedback_actions && display.feedback_actions.length > 0 && (
                <div className="flex flex-wrap gap-2 mt-2 px-1">
                  {display.feedback_actions.map((action) => (
                    <button
                      key={action.type}
                      type="button"
                      disabled={isLoading || !sessionId}
                      onClick={() => onFeedback(action.type, action.label)}
                      className="px-3 py-1.5 bg-indigo-50 border border-indigo-200 text-indigo-700 rounded-full hover:bg-indigo-100 hover:border-indigo-300 font-medium transition-colors text-xs flex items-center gap-1 disabled:opacity-50 focus:outline-none"
                    >
                      {action.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          );
        })}
        <div ref={messagesEndRef} />
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col sm:flex-row gap-3 flex-shrink-0">
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          disabled={!sessionId || isLoading}
          className="flex-1 rounded-lg border border-gray-300 px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:bg-gray-100"
          placeholder="输入您的推荐需求，例如：我想要一款用于日常通勤的无线蓝牙耳机"
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
    </div>
  );
}
