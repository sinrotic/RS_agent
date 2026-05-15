import { useState } from 'react';
import { Image as ImageIcon } from 'lucide-react';
import { DisplayItem } from '../types';

export function ProductCard({ item, onFeedback, disabled }: { item: DisplayItem; onFeedback: (actionType: string, itemId: string) => void; disabled: boolean }) {
  const [imgError, setImgError] = useState(false);
  const price = typeof item.price === 'number' ? `$${item.price.toFixed(2)}` : item.price;

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden flex flex-col h-full transition-shadow hover:shadow-md">
      <div className="h-48 bg-gray-100 flex items-center justify-center relative border-b border-gray-200">
        {item.image_url && !imgError ? (
          <img
            src={item.image_url}
            alt={item.title || item.parent_asin}
            className="w-full h-full object-contain"
            onError={() => setImgError(true)}
          />
        ) : (
          <div className="flex flex-col items-center justify-center text-gray-400">
            <ImageIcon size={48} className="mb-2 opacity-50" />
            <span className="text-sm font-medium">No Image Available</span>
          </div>
        )}
        <div className="absolute top-2 right-2 flex flex-col gap-1">
          {item.badges.map((badge) => (
            <span key={badge} className="bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full opacity-90 shadow-sm whitespace-nowrap">
              {badge.replace(/_/g, ' ')}
            </span>
          ))}
        </div>
      </div>
      <div className="p-4 flex flex-col flex-grow">
        {item.category && <div className="text-xs text-gray-500 mb-1">{item.category}</div>}
        <h3 className="font-semibold text-lg leading-tight mb-2 flex-grow">
          {item.title || `Item ${item.parent_asin}`}
        </h3>
        {price && <div className="font-bold text-gray-900 mb-2">{price}</div>}
        {item.summary && <p className="text-sm text-gray-600 mb-4 line-clamp-2">{item.summary}</p>}
        {item.description && <p className="text-sm text-gray-500 mb-4 line-clamp-3">{item.description}</p>}
        {item.features.length > 0 && (
          <ul className="text-xs text-gray-500 list-disc list-inside mb-4">
            {item.features.slice(0, 3).map((feature) => (
              <li key={feature} className="truncate">{feature}</li>
            ))}
          </ul>
        )}
        <div className="mt-auto space-y-3">
          <div className="flex justify-between items-center text-xs text-gray-500">
            <span>ASIN: {item.parent_asin}</span>
            {item.rating && <span>⭐ {item.rating}</span>}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => onFeedback('like', item.parent_asin)}
              disabled={disabled}
              className="rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1.5 text-xs font-semibold text-emerald-700 hover:bg-emerald-100 disabled:opacity-50"
            >
              喜欢
            </button>
            <button
              type="button"
              onClick={() => onFeedback('dislike', item.parent_asin)}
              disabled={disabled}
              className="rounded-md border border-rose-200 bg-rose-50 px-2 py-1.5 text-xs font-semibold text-rose-700 hover:bg-rose-100 disabled:opacity-50"
            >
              不喜欢
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
