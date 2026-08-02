import { RecommendationGroup } from '../utils/displayViewModel';
import { ProductCard, ProductFeedbackAction } from './ProductCard';

interface GroupedRecommendationGridProps {
  groups: RecommendationGroup[];
  onFeedback: (actionType: ProductFeedbackAction, itemId: string) => void;
  disabled: boolean;
  variant?: 'compact' | 'mall';
}

export function GroupedRecommendationGrid({ groups, onFeedback, disabled, variant = 'compact' }: GroupedRecommendationGridProps) {
  if (groups.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-700 bg-slate-800/40 p-8 text-center text-sm text-slate-400">
        该阶段暂无商品分发，您可以输入意图或者继续与 Agent 互动。
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {groups.map((group) => (
        <section key={group.id} className="space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800/80 pb-2">
            <div className="text-left">
              <h4 className="text-sm font-bold text-slate-100 flex items-center gap-2">
                <span className="w-1.5 h-3.5 bg-indigo-500 rounded-full"></span>
                {group.title}
              </h4>
              <p className="mt-0.5 text-xs text-slate-400 font-medium">{group.description}</p>
            </div>
            <span className="shrink-0 rounded-full bg-indigo-500/10 border border-indigo-500/20 px-2.5 py-0.5 text-[10px] font-bold text-indigo-300">
              {group.items.length} Items
            </span>
          </div>
          <div className={`grid grid-cols-1 gap-4 sm:grid-cols-2 ${variant === 'mall' ? 'lg:grid-cols-3 xl:grid-cols-4' : 'xl:grid-cols-3'}`}>
            {group.items.map((item) => (
              <ProductCard
                key={item.itemId}
                item={item}
                onFeedback={onFeedback}
                disabled={disabled}
                variant={variant}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
