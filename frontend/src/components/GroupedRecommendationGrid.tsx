import { RecommendationGroup } from '../utils/displayViewModel';
import { ProductCard } from './ProductCard';

interface GroupedRecommendationGridProps {
  groups: RecommendationGroup[];
  onFeedback: (actionType: string, itemId: string) => void;
  disabled: boolean;
}

export function GroupedRecommendationGrid({ groups, onFeedback, disabled }: GroupedRecommendationGridProps) {
  if (groups.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-gray-300 bg-white p-6 text-center text-sm text-gray-500">
        这一轮是澄清或解释回复，没有新的商品卡。
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {groups.map((group) => (
        <section key={group.id} className="space-y-3">
          <div className="flex items-end justify-between gap-3">
            <div>
              <h4 className="text-sm font-bold text-gray-900">{group.title}</h4>
              <p className="mt-0.5 text-xs text-gray-500">{group.description}</p>
            </div>
            <span className="shrink-0 rounded-full bg-gray-100 px-2 py-1 text-[10px] font-semibold text-gray-500">
              {group.items.length} 件
            </span>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {group.items.map((item) => (
              <ProductCard
                key={item.parent_asin}
                item={item}
                onFeedback={onFeedback}
                disabled={disabled}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
