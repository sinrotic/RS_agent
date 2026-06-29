import { MessageSquare, ThumbsUp, ThumbsDown, RefreshCw, HelpCircle } from 'lucide-react';

export interface FeedbackAction {
  type: 'like' | 'dislike' | 'show_different' | 'why' | 'chat';
  label: string;
}

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
          className={`flex items-center gap-2 rounded-full border border-indigo-500/20 bg-indigo-500/10 font-medium text-indigo-300 shadow-sm transition-all hover:bg-indigo-500/20 hover:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-40 cursor-pointer ${compact ? 'px-3 py-1 text-xs' : 'px-4 py-1.5 text-sm'}`}
        >
          {actionIcon(action.type, compact ? 12 : 14)}
          {action.label}
        </button>
      ))}
    </div>
  );
}
