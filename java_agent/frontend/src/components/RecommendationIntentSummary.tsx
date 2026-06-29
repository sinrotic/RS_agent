import { Sparkles } from 'lucide-react';
import { DisplayViewModel } from '../utils/displayViewModel';

interface RecommendationIntentSummaryProps {
  viewModel: DisplayViewModel;
}

export function RecommendationIntentSummary({ viewModel }: RecommendationIntentSummaryProps) {
  const { intentSummary, referenceContext } = viewModel;

  return (
    <div className="rounded-2xl border border-slate-700/80 bg-gradient-to-br from-slate-800 via-slate-800/90 to-slate-900/90 p-4 text-left shadow-md">
      <div className="flex items-start gap-3">
        <div className="rounded-full bg-indigo-500/10 border border-indigo-500/25 p-2 text-indigo-400">
          <Sparkles size={16} className="animate-pulse" />
        </div>
        <div className="min-w-0 flex-1">
          <h4 className="text-sm font-bold text-slate-100">{intentSummary.title}</h4>
          <p className="mt-1 text-xs leading-relaxed text-slate-350">{intentSummary.subtitle}</p>
          {intentSummary.chips.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {intentSummary.chips.map((chip) => (
                <span key={chip} className="rounded-full border border-slate-700 bg-slate-900/60 px-2.5 py-0.5 text-[10px] font-semibold text-indigo-300 shadow-sm">
                  {chip}
                </span>
              ))}
            </div>
          )}
          {referenceContext && (
            <div className="mt-3 rounded-xl border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-[10px] leading-relaxed text-amber-400">
              {referenceContext.label}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
