import { useState } from 'react';
import { HelpCircle, Heart, Image as ImageIcon, XCircle } from 'lucide-react';
import { DisplayProduct, userFacingBadgeLabel } from '../utils/displayViewModel';

export type ProductFeedbackAction = 'like' | 'dislike' | 'why';

interface ProductCardProps {
  item: DisplayProduct;
  onFeedback: (actionType: ProductFeedbackAction, itemId: string) => void;
  disabled: boolean;
  variant?: 'compact' | 'mall';
}

export function ProductCard({ item, onFeedback, disabled, variant = 'compact' }: ProductCardProps) {
  const [imgError, setImgError] = useState(false);
  const price = typeof item.price === 'number' ? `$${item.price.toFixed(2)}` : null;
  const visibleBadges = (item.badges || [])
    .map((badge) => userFacingBadgeLabel(badge))
    .filter(Boolean)
    .slice(0, 3) as string[];

  const imageHeight = variant === 'mall' ? 'h-48' : 'h-36';

  return (
    <div className="bg-slate-800/80 rounded-2xl border border-slate-700/60 overflow-hidden flex flex-col h-full transition-all duration-300 hover:shadow-lg hover:shadow-indigo-500/10 hover:-translate-y-1 hover:border-slate-600/80">
      {/* Product Image Panel */}
      <div className={`${imageHeight} bg-slate-950/60 flex items-center justify-center relative overflow-hidden group`}>
        {item.imageUrl && !imgError ? (
          <img
            src={item.imageUrl}
            alt={item.title || item.itemId}
            className="w-full h-full object-contain p-3 transition-transform duration-500 group-hover:scale-105"
            onError={() => setImgError(true)}
          />
        ) : (
          <div className="flex flex-col items-center justify-center text-slate-500">
            <ImageIcon size={36} className="mb-1 opacity-40 animate-pulse" />
            <span className="text-xs font-medium">No Image</span>
          </div>
        )}

        {/* Floating Badges */}
        {visibleBadges.length > 0 && (
          <div className="absolute top-2.5 right-2.5 flex flex-col gap-1 items-end z-10">
            {visibleBadges.map((badge) => (
              <span key={badge} className="bg-indigo-500/90 text-white text-[9px] font-bold px-2 py-0.5 rounded-full shadow-md backdrop-blur-sm tracking-wide">
                {badge}
              </span>
            ))}
          </div>
        )}

        {/* Score indicator */}
        <div className="absolute bottom-2 left-2.5 bg-slate-900/80 backdrop-blur-md border border-slate-700/50 px-2 py-0.5 rounded text-[10px] font-mono text-indigo-300 font-semibold shadow-sm">
          Score: {item.score.toFixed(3)}
        </div>
      </div>

      {/* Info Details */}
      <div className="p-4 flex flex-col flex-grow text-left">
        <div className="flex items-center justify-between gap-2 mb-1.5">
          {item.category && <div className="text-[10px] font-bold text-indigo-400 uppercase tracking-wider truncate max-w-[60%]">{item.category.split('/').pop() || item.category}</div>}
          {item.store && <div className="text-[10px] text-slate-400 font-medium truncate max-w-[40%]">{item.store}</div>}
        </div>

        <h3 className="font-semibold text-sm leading-snug mb-2 flex-grow text-slate-100 line-clamp-2 hover:text-indigo-300 transition-colors">
          {item.title || `Item ${item.itemId}`}
        </h3>

        <div className="mb-3.5 flex items-baseline justify-between">
          <div className="font-extrabold text-base text-slate-100">
            {price || '$--'}
          </div>
          {item.rating && (
            <div className="flex items-center gap-0.5 text-xs text-amber-400 font-semibold bg-amber-500/10 px-1.5 py-0.5 rounded-md">
              ⭐ {item.rating.toFixed(1)}
            </div>
          )}
        </div>

        {/* AI Recommendation Reason */}
        <div className="mb-4 rounded-xl border border-indigo-500/10 bg-indigo-950/30 px-3 py-2.5">
          <div className="text-[9px] font-bold text-indigo-400 uppercase tracking-widest mb-1">AI 推荐理由</div>
          <p className="text-[11px] leading-relaxed text-slate-350 line-clamp-3 font-normal">{item.reason}</p>
        </div>

        {/* Actions button */}
        <div className="mt-auto space-y-2.5">
          <div className="text-[9px] text-slate-500 font-mono">ASIN: {item.itemId}</div>
          <div className="flex flex-col gap-2">
            <button
              type="button"
              onClick={() => onFeedback('like', item.itemId)}
              disabled={disabled}
              className="w-full inline-flex items-center justify-center gap-1.5 rounded-lg border border-emerald-500/20 bg-emerald-500/10 hover:bg-emerald-500/25 px-3 py-1.5 text-xs font-bold text-emerald-400 hover:text-white transition-all disabled:opacity-40 disabled:hover:bg-emerald-500/10 cursor-pointer"
            >
              <Heart size={12} className="fill-current" />
              喜欢，找相似
            </button>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => onFeedback('dislike', item.itemId)}
                disabled={disabled}
                className="inline-flex items-center justify-center gap-1 rounded-lg border border-rose-500/20 bg-rose-500/10 hover:bg-rose-500/25 px-2 py-1.5 text-xs font-bold text-rose-450 hover:text-white transition-all disabled:opacity-40 disabled:hover:bg-rose-500/10 cursor-pointer"
              >
                <XCircle size={12} />
                不感兴趣
              </button>
              <button
                type="button"
                onClick={() => onFeedback('why', item.itemId)}
                disabled={disabled}
                className="inline-flex items-center justify-center gap-1 rounded-lg border border-slate-700 bg-slate-800 hover:bg-slate-750 px-2 py-1.5 text-xs font-bold text-slate-300 hover:text-white transition-all disabled:opacity-40 disabled:hover:bg-slate-800 cursor-pointer"
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
