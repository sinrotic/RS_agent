import { FormEvent, useEffect, useRef } from 'react';
import { Send, Play, History, MessageSquare } from 'lucide-react';
import { ChatMessage, DisplayResponse } from '../types';

interface ChatPanelProps {
  display: DisplayResponse;
  status: string;
  messages: ChatMessage[];
  input: string;
  setInput: (value: string) => void;
  isLoading: boolean;
  sessionId: string;
  demoLoading: boolean;
  replayLoading: boolean;
  onDemoRoundtrip: () => void;
  onReplay: () => void;
  onSubmit: (message: string) => void;
}

export function ChatPanel({
  display, status, messages, input, setInput, isLoading, sessionId,
  demoLoading, replayLoading, onDemoRoundtrip, onReplay, onSubmit
}: ChatPanelProps) {
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit(input);
  }

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 flex flex-col gap-4">
      <div className="flex items-start gap-4">
        <div className="bg-indigo-100 p-3 rounded-full flex-shrink-0">
          <MessageSquare className="text-indigo-600" size={24} />
        </div>
        <div className="flex-1">
          <div className="flex justify-between items-start gap-4">
            <div>
              <h1 className="text-xl font-bold text-gray-900 mb-1">RS Agent Live Demo</h1>
              <p className="text-gray-700">{display.assistant_message}</p>
            </div>
            <div className="flex flex-wrap justify-end gap-2">
              <button
                type="button"
                onClick={onDemoRoundtrip}
                disabled={demoLoading || isLoading}
                className="flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 whitespace-nowrap"
              >
                <Play size={16} />
                {demoLoading ? 'Running...' : '一键闭环'}
              </button>
              <button
                type="button"
                onClick={onReplay}
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
  );
}
