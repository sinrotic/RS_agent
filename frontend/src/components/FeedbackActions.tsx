import { MessageSquare, ThumbsUp, ThumbsDown, RefreshCw, HelpCircle } from 'lucide-react';
import { FeedbackAction } from '../types';

function actionIcon(type: string) {
  switch (type) {
    case 'like': return <ThumbsUp size={16} />;
    case 'dislike': return <ThumbsDown size={16} />;
    case 'show_different': return <RefreshCw size={16} />;
    case 'why': return <HelpCircle size={16} />;
    default: return <MessageSquare size={16} />;
  }
}

interface FeedbackActionsProps {
  actions: FeedbackAction[];
  onAction: (action: FeedbackAction) => void;
  disabled: boolean;
}

export function FeedbackActions({ actions, onAction, disabled }: FeedbackActionsProps) {
  return (
    <div className="flex flex-wrap gap-3 justify-center pt-4">
      {actions.map((action) => (
        <button
          key={action.type}
          onClick={() => onAction(action)}
          disabled={disabled}
          className="flex items-center gap-2 px-4 py-2 bg-white border border-gray-300 rounded-full shadow-sm hover:bg-gray-50 hover:border-gray-400 transition-colors text-sm font-medium text-gray-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 disabled:opacity-50"
        >
          {actionIcon(action.type)}
          {action.label}
        </button>
      ))}
    </div>
  );
}
