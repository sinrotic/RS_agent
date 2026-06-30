import { MessageSquare, ThumbsUp, ThumbsDown, RefreshCw, HelpCircle } from 'lucide-react';
import { FeedbackAction } from '../types';

function actionIcon(type: string, size: number) {
  switch (type) {
    case 'like': return <ThumbsUp size={size} />;
    case 'dislike': return <ThumbsDown size={size} />;
    case 'show_different': return <RefreshCw size={size} />;
    case 'why': return <HelpCircle size={size} />;
    default: return <MessageSquare size={size} />;
  }
}

interface FeedbackActionsProps {
  actions: FeedbackAction[];
  onAction: (action: FeedbackAction) => void;
  disabled: boolean;
  size?: 'sm' | 'md';
  align?: 'left' | 'center';
}

export function FeedbackActions({ actions, onAction, disabled, size = 'md', align = 'center' }: FeedbackActionsProps) {
  const compact = size === 'sm';
  return (
    <div className={`flex flex-wrap gap-2 ${align === 'left' ? 'justify-start' : 'justify-center'} ${compact ? 'pt-2' : 'pt-4'}`}>
      {actions.map((action) => (
        <button
          key={action.type}
          type="button"
          onClick={() => onAction(action)}
          disabled={disabled}
          className={`flex items-center gap-2 rounded-full border border-indigo-200 bg-indigo-50 font-medium text-indigo-700 shadow-sm transition-colors hover:border-indigo-300 hover:bg-indigo-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 disabled:opacity-50 ${compact ? 'px-3 py-1.5 text-xs' : 'px-4 py-2 text-sm'}`}
        >
          {actionIcon(action.type, compact ? 13 : 16)}
          {action.label}
        </button>
      ))}
    </div>
  );
}
