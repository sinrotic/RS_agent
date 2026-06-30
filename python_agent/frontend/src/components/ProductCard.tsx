import { useState } from 'react';
import { HelpCircle, Heart, Image as ImageIcon, XCircle } from 'lucide-react';
import { DisplayItem } from '../types';
import { recommendationReason, userFacingBadgeLabel } from '../utils/displayViewModel';

interface ProductCardProps {
  item: DisplayItem;
  onFeedback: (actionType: string, itemId: string) => void;
  disabled: boolean;
  variant?: 'compact' | 'mall';
}

export function ProductCard({ item, onFeedback, disabled, variant = 'compact' }: ProductCardProps) {
  const [imgError, setImgError] = useState(false);
  const price = typeof item.price === 'number' ? `$${item.price.toFixed(2)}` : item.price;
  const features = item.features || [];
  const visibleBadges = (item.badges || [])
    .map((badge) => userFacingBadgeLabel(badge))
    .filter(Boolean)
    .slice(0, 3) as string[];
  const reason = recommendationReason({ ...item, features });
  const imageHeight = variant === 'mall' ? 'h-56' : 'h-44';

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden flex flex-col h-full transition-all hover:shadow-md hover:-translate-y-0.5">
      <div className={`${imageHeight} bg-gray-100 flex items-center justify-center relative border-b border-gray-200`}>
        {item.image_url && !imgError ? (
          <img
            src={item.image_url}
            alt={item.title || item.parent_asin}
            className="w-full h-full object-contain p-2"
            onError={() => setImgError(true)}
          />
        ) : (
          <div className="flex flex-col items-center justify-center text-gray-400">
            <ImageIcon size={42} className="mb-2 opacity-50" />
            <span className="text-sm font-medium">暂无商品图片</span>
          </div>
        )}
        {visibleBadges.length > 0 && (
          <div className="absolute top-2 right-2 flex max-w-[80%] flex-col items-end gap-1">
            {visibleBadges.map((badge) => (
              <span key={badge} className="bg-blue-100 text-blue-800 text-[10px] px-2 py-1 rounded-full opacity-95 shadow-sm whitespace-nowrap">
                {badge}
              </span>
            ))}
          </div>
        )}
      </div>
      <div className="p-4 flex flex-col flex-grow">
        <div className="flex items-center justify-between gap-2 mb-2">
          {item.category && <div className="text-xs font-semibold text-indigo-600 truncate">{item.category}</div>}
          {item.store && <div className="text-[10px] text-gray-400 truncate">{item.store}</div>}
        </div>
        <h3 className="font-semibold text-base leading-tight mb-2 flex-grow text-gray-900 line-clamp-2">
          {item.title || `商品 ${item.parent_asin}`}
        </h3>
        <div className="mb-3 flex items-center justify-between gap-2">
          {price && <div className="font-bold text-gray-900">{price}</div>}
          {item.rating && <span className="text-xs text-amber-600">⭐ {item.rating}</span>}
        </div>

        <div className="mb-3 rounded-lg border border-indigo-50 bg-indigo-50/70 px-3 py-2">
          <div className="text-[10px] font-bold text-indigo-500 mb-1">推荐理由</div>
          <p className="text-xs leading-relaxed text-gray-600 line-clamp-3">{reason}</p>
        </div>

        {item.description && !item.summary && (
          <p className="text-xs text-gray-500 mb-3 line-clamp-2">{item.description}</p>
        )}
        {features.length > 0 && (
          <ul className="text-[11px] text-gray-500 space-y-1 mb-4">
            {features.slice(0, 3).map((feature) => (
              <li key={feature} className="truncate">• {feature}</li>
            ))}
          </ul>
        )}
        <div className="mt-auto space-y-3">
          <div className="text-[10px] text-gray-400 font-mono truncate">ASIN: {item.parent_asin}</div>
          <div className="grid grid-cols-1 gap-2">
            <button
              type="button"
              onClick={() => onFeedback('like', item.parent_asin)}
              disabled={disabled}
              className="inline-flex items-center justify-center gap-1.5 rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1.5 text-xs font-semibold text-emerald-700 hover:bg-emerald-100 disabled:opacity-50"
            >
              <Heart size={13} />
              喜欢，找相似
            </button>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => onFeedback('dislike', item.parent_asin)}
                disabled={disabled}
                className="inline-flex items-center justify-center gap-1 rounded-md border border-rose-200 bg-rose-50 px-2 py-1.5 text-xs font-semibold text-rose-700 hover:bg-rose-100 disabled:opacity-50"
              >
                <XCircle size={12} />
                不感兴趣
              </button>
              <button
                type="button"
                onClick={() => onFeedback('why', item.parent_asin)}
                disabled={disabled}
                className="inline-flex items-center justify-center gap-1 rounded-md border border-gray-200 bg-gray-50 px-2 py-1.5 text-xs font-semibold text-gray-700 hover:bg-gray-100 disabled:opacity-50"
              >
                <HelpCircle size={12} />
                为什么推荐
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
