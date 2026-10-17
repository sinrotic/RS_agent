import { useEffect, useState } from 'react';
import { ArrowLeft, Image as ImageIcon, Loader2, RefreshCw } from 'lucide-react';
import { fetchCatalogItemDetail } from '../api/catalogClient';
import { fetchInventoryAvailability } from '../api/inventoryClient';
import { ApiError } from '../api/shared';
import { CatalogItemDetail } from '../types/catalog';
import { InventoryAvailability } from '../types/inventory';
import { DisplayProduct, userFacingBadgeLabel } from '../utils/displayViewModel';
import { CheckoutPanel } from '../components/CheckoutPanel';

interface ProductDetailProps {
  itemId: string;
  fallbackProduct?: DisplayProduct | null;
  onBack: () => void;
}

export function ProductDetail({ itemId, fallbackProduct, onBack }: ProductDetailProps) {
  const [detail, setDetail] = useState<CatalogItemDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [imageError, setImageError] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [inventory, setInventory] = useState<InventoryAvailability | null>(null);
  const [inventoryLoading, setInventoryLoading] = useState(true);
  const [inventoryError, setInventoryError] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setNotFound(false);
    fetchCatalogItemDetail(itemId)
      .then(value => active && setDetail(value))
      .catch(reason => {
        if (!active) return;
        if (reason instanceof ApiError && reason.status === 404) {
          setNotFound(true);
          setDetail(null);
          return;
        }
        setError(reason instanceof Error ? reason.message : '无法加载商品详情');
      })
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [itemId, reloadKey]);

  useEffect(() => {
    let active = true;
    setInventory(null);
    setInventoryLoading(true);
    setInventoryError(false);
    fetchInventoryAvailability(itemId)
      .then(value => active && setInventory(value))
      .catch(() => active && setInventoryError(true))
      .finally(() => active && setInventoryLoading(false));
    return () => { active = false; };
  }, [itemId, reloadKey]);

  useEffect(() => {
    setImageError(false);
  }, [itemId]);

  if (notFound) {
    return (
      <div className="flex-1 overflow-y-auto text-left">
        <div className="mx-auto max-w-3xl py-16">
          <button type="button" onClick={onBack} className="inline-flex items-center gap-2 text-sm font-semibold text-slate-400 hover:text-white">
            <ArrowLeft size={16} /> 返回
          </button>
          <h1 className="mt-10 text-2xl font-bold text-slate-100">商品不存在或已下架</h1>
          <p className="mt-3 text-sm text-slate-400">Catalog 中没有可展示的商品记录。</p>
        </div>
      </div>
    );
  }

  const title = detail?.title || fallbackProduct?.title || '商品详情';
  const imageUrl = detail?.imageUrl || fallbackProduct?.imageUrl;
  const price = detail?.price ?? fallbackProduct?.price;
  const category = detail?.category || fallbackProduct?.category;
  const store = detail?.storeName || fallbackProduct?.store;
  const badges = (fallbackProduct?.badges || [])
    .map(userFacingBadgeLabel)
    .filter(Boolean) as string[];

  return (
    <div className="flex-1 overflow-y-auto text-left">
      <div className="mx-auto max-w-6xl space-y-6">
        <button type="button" onClick={onBack} className="inline-flex items-center gap-2 text-sm font-semibold text-slate-400 hover:text-white transition-colors cursor-pointer">
          <ArrowLeft size={16} /> 返回推荐首页
        </button>

        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
          <div className="min-h-[360px] rounded-2xl border border-slate-700/70 bg-slate-900/80 p-6 flex items-center justify-center">
            {imageUrl && !imageError ? (
              <img src={imageUrl} alt={title} onError={() => setImageError(true)} className="max-h-[420px] w-full object-contain" />
            ) : (
              <div className="flex flex-col items-center gap-2 text-slate-500"><ImageIcon size={48} /><span>暂无商品图片</span></div>
            )}
          </div>

          <div className="space-y-5">
            <div className="space-y-3">
              <div className="flex flex-wrap gap-2">
                {category && <span className="rounded-full bg-indigo-500/15 px-3 py-1 text-xs font-semibold text-indigo-300">{category}</span>}
                {badges.map(badge => <span key={badge} className="rounded-full bg-slate-800 px-3 py-1 text-xs font-semibold text-slate-300">{badge}</span>)}
              </div>
              <h1 className="text-3xl font-extrabold tracking-tight text-slate-100">{title}</h1>
              <p className="text-sm text-slate-400">商品编号：{itemId}{store ? ` · ${store}` : ''}</p>
            </div>

            <div className="grid gap-5 border-y border-slate-800 py-5 sm:grid-cols-2">
              <div><div className="text-xs font-semibold uppercase tracking-widest text-slate-500">参考价格</div><div className="mt-1 text-3xl font-extrabold text-white">{typeof price === 'number' ? `$${price.toFixed(2)}` : '暂无报价'}</div></div>
              <div>
                <div className="text-xs font-semibold uppercase tracking-widest text-slate-500">库存状态</div>
                <div className="mt-2 text-sm font-semibold text-slate-200">
                  {inventoryLoading && '正在查询...'}
                  {!inventoryLoading && inventoryError && '库存状态暂不可用'}
                  {!inventoryLoading && !inventoryError && !inventory && '暂无库存信息'}
                  {!inventoryLoading && !inventoryError && inventory?.available && `有货 · ${inventory.availableStock} 件可售`}
                  {!inventoryLoading && !inventoryError && inventory && !inventory.available && '暂时无货'}
                </div>
              </div>
            </div>

            {loading && <div className="flex items-center gap-2 text-sm text-indigo-300"><Loader2 size={16} className="animate-spin" />正在加载目录详情...</div>}
            {error && (
              <div className="flex items-center justify-between gap-4 border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-300">
                <span>商品详情暂不可用：{error}</span>
                <button type="button" onClick={() => setReloadKey(value => value + 1)} className="shrink-0 p-2 text-rose-200 hover:text-white" title="重新加载">
                  <RefreshCw size={16} />
                </button>
              </div>
            )}
            <p className="text-sm leading-7 text-slate-300">{detail?.description || detail?.summary || fallbackProduct?.description || '暂无商品描述。'}</p>

            <CheckoutPanel key={itemId} itemId={itemId} sessionId={fallbackProduct?.sessionId}
              recommendRequestId={fallbackProduct?.recommendRequestId} />

            {detail?.attributes && Object.keys(detail.attributes).length > 0 && (
              <dl className="divide-y divide-slate-800 rounded-xl border border-slate-800 bg-slate-900/50 px-4">
                {Object.entries(detail.attributes).map(([label, value]) => <div key={label} className="grid grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] gap-4 py-3 text-sm"><dt className="text-slate-500">{label}</dt><dd className="text-slate-200">{value}</dd></div>)}
              </dl>
            )}

            {fallbackProduct?.reason && <div className="rounded-xl border border-indigo-500/20 bg-indigo-950/30 p-4"><div className="text-xs font-bold uppercase tracking-widest text-indigo-300">为什么推荐</div><p className="mt-2 text-sm leading-6 text-slate-300">{fallbackProduct.reason}</p></div>}
          </div>
        </div>
      </div>
    </div>
  );
}
