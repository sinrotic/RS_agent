import { DisplayItem } from '../types';
import { ProductCard } from './ProductCard';

export function ProductGrid({ items, onFeedback, disabled }: { items: DisplayItem[]; onFeedback: (actionType: string, itemId: string) => void; disabled: boolean }) {
  if (items.length === 0) {
    return (
      <div className="bg-white rounded-lg border border-dashed border-gray-300 p-8 text-center text-gray-500">
        这一轮是澄清或解释回复，没有新的商品卡。
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
      {items.map((item) => (
        <ProductCard key={item.parent_asin} item={item} onFeedback={onFeedback} disabled={disabled} />
      ))}
    </div>
  );
}
