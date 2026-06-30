import { Sparkles } from 'lucide-react';
import { DisplayViewModel } from '../utils/displayViewModel';

interface RecommendationIntentSummaryProps {
  viewModel: DisplayViewModel;
}

export function RecommendationIntentSummary({ viewModel }: RecommendationIntentSummaryProps) {
  const { intentSummary, referenceContext } = viewModel;

  return (
    <div className="rounded-2xl border border-indigo-100 bg-gradient-to-br from-indigo-50 via-white to-sky-50 p-4 text-left shadow-sm">
      <div className="flex items-start gap-3">
        <div className="rounded-full bg-indigo-100 p-2 text-indigo-600">
          <Sparkles size={16} />
        </div>
        <div className="min-w-0 flex-1">
          <h4 className="text-sm font-bold text-gray-900">{intentSummary.title}</h4>
          <p className="mt-1 text-xs leading-relaxed text-gray-600">{intentSummary.subtitle}</p>
          {intentSummary.chips.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {intentSummary.chips.map((chip) => (
                <span key={chip} className="rounded-full border border-indigo-100 bg-white px-2.5 py-1 text-[11px] font-medium text-indigo-700 shadow-sm">
                  {chip}
                </span>
              ))}
            </div>
          )}
          {referenceContext && (
            <div className="mt-3 rounded-xl border border-amber-100 bg-amber-50 px-3 py-2 text-[11px] leading-relaxed text-amber-800">
              {referenceContext.label}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
