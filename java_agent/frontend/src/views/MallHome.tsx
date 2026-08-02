import { useState, useEffect } from 'react';
import { RefreshCw, Heart, Compass, Cpu, EyeOff } from 'lucide-react';
import { recommendHome, refreshHome } from '../api/recommendClient';
import { recordEvent, recordExposure } from '../api/interactionClient';
import { startSession } from '../api/sessionClient';
import { buildDisplayViewModel, DisplayProduct, DisplayViewModel } from '../utils/displayViewModel';
import { GroupedRecommendationGrid } from '../components/GroupedRecommendationGrid';
import { RecommendationIntentSummary } from '../components/RecommendationIntentSummary';
import { ProductFeedbackAction } from '../components/ProductCard';
import { getStoredProfileUserId } from '../api/shared';
import { enrichRecommendedProducts } from '../utils/catalogEnrichment';

export function MallHome() {
  const [profileUserId, setProfileUserId] = useState<string>('');
  const [sessionId, setSessionId] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);
  const [status, setStatus] = useState<string>('Initializing Mall Feed...');
  const [products, setProducts] = useState<DisplayProduct[]>([]);
  const [viewModel, setViewModel] = useState<DisplayViewModel | null>(null);
  const [lastRequestId, setLastRequestId] = useState<string>('');
  const [catalogUnavailable, setCatalogUnavailable] = useState<boolean>(false);
  const [feedError, setFeedError] = useState<string | null>(null);

  // Wishlist state
  const [wishlist, setWishlist] = useState<DisplayProduct[]>([]);

  // Obs Details
  const [selectedProduct, setSelectedProduct] = useState<DisplayProduct | null>(null);
  const [explanation, setExplanation] = useState<string>('');
  const [explaining, setExplaining] = useState<boolean>(false);

  // Read stored user on mount
  useEffect(() => {
    const stored = getStoredProfileUserId() || 'guest_user';
    setProfileUserId(stored);
    handleInitialize(stored);
  }, []);

  const handleInitialize = async (userId: string) => {
    setLoading(true);
    setFeedError(null);
    setStatus('正在创建推荐会话并生成初始个性化商品流...');
    try {
      // 1. Start session
      const sessionRes = await startSession(userId);
      setSessionId(sessionRes.sessionId);

      // 2. Fetch recommend items
      const recRes = await recommendHome({
        profileUserId: userId,
        scene: 'home',
        limit: 6,
        debug: true
      });
      setLastRequestId(recRes.request_id);

      // 3. Enrich recommendation metadata with Catalog card details when available.
      const itemIds = recRes.items.map(item => item.item_id);
      const { products: mergedProducts, catalogAvailable } = await enrichRecommendedProducts(recRes.items);
      setCatalogUnavailable(!catalogAvailable);
      setProducts(mergedProducts);

      // 5. Build viewModel
      const vm = buildDisplayViewModel(recRes, mergedProducts, '', null, '为您定制了以下数码配件精选列表：');
      setViewModel(vm);

      // 6. Record Exposure
      await recordExposure({
        request_id: recRes.request_id,
        session_id: sessionRes.sessionId,
        item_ids: itemIds,
        exposed_at: Date.now()
      });

      setStatus(catalogAvailable
        ? '个性化推荐加载成功！'
        : '推荐已加载，商品详情服务暂时不可用，当前展示推荐摘要。');
    } catch (e: any) {
      console.error(e);
      const message = `初始化推荐失败: ${e.message}`;
      setFeedError(message);
      setStatus(message);
    } finally {
      setLoading(false);
    }
  };

  const handleRefresh = async () => {
    if (!sessionId || loading) return;
    setLoading(true);
    setFeedError(null);
    setStatus('正在根据交互历史刷新重排首页推荐...');
    try {
      const recRes = await refreshHome({
        sessionId,
        profileUserId,
        scene: 'home',
        limit: 6,
        refreshAction: 'rerecall_pool500'
      });
      setLastRequestId(recRes.request_id);

      const itemIds = recRes.items.map(item => item.item_id);
      const { products: mergedProducts, catalogAvailable } = await enrichRecommendedProducts(recRes.items);
      setCatalogUnavailable(!catalogAvailable);
      setProducts(mergedProducts);

      const vm = buildDisplayViewModel(recRes, mergedProducts, '点击刷新', { actionType: 'show_different', label: '换一批' }, '已完成推荐流重排与多样化探索：');
      setViewModel(vm);

      await recordExposure({
        request_id: recRes.request_id,
        session_id: sessionId,
        item_ids: itemIds,
        exposed_at: Date.now()
      });

      setStatus(catalogAvailable
        ? '首页推荐流刷新成功！'
        : '推荐已刷新，商品详情服务暂时不可用，当前展示推荐摘要。');
    } catch (e: any) {
      const message = `刷新失败: ${e.message}`;
      setFeedError(message);
      setStatus(message);
    } finally {
      setLoading(false);
    }
  };

  const handleFeedback = async (actionType: ProductFeedbackAction, itemId: string) => {
    if (!sessionId || loading) return;

    if (actionType === 'why') {
      const item = products.find(p => p.itemId === itemId);
      if (item) {
        setSelectedProduct(item);
        setExplanation('');
        setExplaining(true);
        // Simulate RAG / model score trace explanation
        setTimeout(() => {
          setExplanation(`[特征归因解释]
对商品 「${item.title}」 的推荐得分 = ${(item.score * 100).toFixed(1)} 分。
主要影响因子分析：
- 偏好召回得分 (Collaborative Recall): ${(item.score * 0.4).toFixed(3)}
- 用户兴趣画像匹配度 (Profile Alignment): ${(item.score * 0.35).toFixed(3)}
- 热度趋势惩罚与加权 (Trend weight): +${(item.score * 0.15).toFixed(3)}
- 自然语言交互反馈匹配度 (Interactive refinement): +${(item.score * 0.1).toFixed(3)}
解释摘要：此商品源于您的画像分组。您的反馈 “点赞” 将进一步放大相关品类的权重。`);
          setExplaining(false);
        }, 600);
      }
      return;
    }

    setLoading(true);
    setFeedError(null);
    const label = actionType === 'like' ? '喜欢，找相似' : '不感兴趣';
    setStatus(`已捕获交互信号 [${label}]，正在更新推荐兴趣模型...`);

    try {
      // 1. Record event
      await recordEvent({
        request_id: lastRequestId || 'request',
        session_id: sessionId,
        item_id: itemId,
        event_type: actionType,
        event_value: actionType === 'like' ? 1.0 : -1.0,
        occurred_at: Date.now()
      });

      // 2. Perform local update or request reload
      if (actionType === 'like') {
        const likedItem = products.find(p => p.itemId === itemId);
        if (likedItem && !wishlist.some(w => w.itemId === itemId)) {
          setWishlist(prev => [...prev, likedItem]);
        }
      }

      // Re-trigger recommend refresh
      const recRes = await refreshHome({
        sessionId,
        profileUserId,
        scene: 'home',
        limit: 6,
        refreshAction: 'rerank_existing'
      });
      setLastRequestId(recRes.request_id);

      const { products: mergedProducts, catalogAvailable } = await enrichRecommendedProducts(recRes.items);
      setCatalogUnavailable(!catalogAvailable);
      setProducts(mergedProducts);

      const vm = buildDisplayViewModel(
        recRes,
        mergedProducts,
        actionType === 'like' ? `喜欢商品 ${itemId}` : `踩商品 ${itemId}`,
        { actionType, label, itemId },
        '推荐引擎已自动完成排序重构，适配您的最新意向：'
      );
      setViewModel(vm);

      setStatus(catalogAvailable
        ? '模型状态已同步更新，推荐网格已重排！'
        : '推荐已重排，商品详情服务暂时不可用，当前展示推荐摘要。');
    } catch (e: any) {
      const message = `反馈提交失败: ${e.message}`;
      setFeedError(message);
      setStatus(message);
    } finally {
      setLoading(false);
    }
  };

  // Removed unused addToCart helper

  return (
    <div className="flex-1 flex flex-col gap-6 text-slate-100 overflow-y-auto min-h-0 text-left">
      {/* Top Banner */}
      <div className="relative rounded-2xl bg-gradient-to-r from-indigo-600 via-indigo-900 to-slate-950 p-6 md:p-8 shadow-xl overflow-hidden flex-shrink-0">
        <div className="absolute inset-0 bg-[linear-gradient(to_right,#80808012_1px,transparent_1px),linear-gradient(to_bottom,#80808012_1px,transparent_1px)] bg-[size:24px_24px] opacity-15"></div>
        <div className="relative z-10 flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
          <div className="space-y-2">
            <div className="inline-flex items-center gap-1.5 px-3 py-1 bg-white/10 backdrop-blur-md rounded-full text-[10px] font-bold text-indigo-300 tracking-wide uppercase">
              <Compass size={12} className="animate-spin-slow" />
              Java Microservices Recommendation Sandbox
            </div>
            <h1 className="text-2xl md:text-3xl font-extrabold tracking-tight">
              千人千面个性化商城
            </h1>
            <p className="text-slate-400 text-xs md:text-sm max-w-xl">
              结合 <span className="text-indigo-400 font-semibold">{profileUserId}</span> 的画像特征。当您与推荐网格下的交互按钮发生动作时，底层的交互服务会记录曝光、点击、好恶反馈。
            </p>
          </div>

          <div className="flex flex-wrap gap-3">
            <button
              onClick={handleRefresh}
              disabled={loading || !sessionId}
              className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white transition-all font-bold rounded-xl px-5 py-3 text-xs flex items-center gap-1.5 shadow-lg shadow-indigo-600/25 cursor-pointer"
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              换一批推荐
            </button>
          </div>
        </div>
      </div>

      {/* Main Grid: Left for Feed / Right for cart&detail */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 items-start">
        {/* Recommend Feed */}
        <div className="lg:col-span-3 space-y-6">
          {viewModel && <RecommendationIntentSummary viewModel={viewModel} />}

          {catalogUnavailable && (
            <div role="status" className="border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-xs text-amber-200">
              商品详情暂时无法加载，正在展示推荐结果。
            </div>
          )}

          {feedError ? (
            <div role="alert" className="border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
              {feedError}
            </div>
          ) : loading ? (
            <div className="py-20 flex flex-col items-center justify-center gap-3">
              <div className="w-10 h-10 border-4 border-indigo-500/30 border-t-indigo-500 rounded-full animate-spin"></div>
              <div className="text-xs text-indigo-400 font-bold tracking-widest uppercase">{status}</div>
            </div>
          ) : (
            viewModel && (
              <GroupedRecommendationGrid
                groups={viewModel.groups}
                onFeedback={handleFeedback}
                disabled={loading || !sessionId}
                variant="mall"
              />
            )
          )}
        </div>

        {/* Sidebar Info Panels */}
        <div className="space-y-6 lg:col-span-1">
          {/* Status Alert */}
          <div className="bg-slate-800/80 border border-slate-700/60 rounded-2xl p-4 text-xs font-semibold">
            <div className="text-slate-400 uppercase tracking-widest text-[9px] mb-1">系统事件流</div>
            <p className="text-indigo-300 leading-snug font-medium">{status}</p>
          </div>

          {/* Cart & Wishlist */}
          <div className="bg-slate-800/80 border border-slate-700/60 rounded-2xl p-4 space-y-4">
            <div className="flex items-center justify-between border-b border-slate-700/50 pb-2">
              <span className="text-xs font-bold text-slate-100 flex items-center gap-1.5">
                <Heart size={14} className="text-rose-500 fill-current" />
                个性化收藏 ({wishlist.length})
              </span>
            </div>
            {wishlist.length === 0 ? (
              <div className="text-[11px] text-slate-500 italic py-2">暂无收藏。点赞的商品将自动收录此处。</div>
            ) : (
              <div className="space-y-2">
                {wishlist.map(w => (
                  <div key={w.itemId} className="flex gap-2 items-center bg-slate-900/40 p-2 rounded-xl border border-slate-700/40">
                    <img src={w.imageUrl || ''} className="w-8 h-8 object-contain rounded bg-slate-950" />
                    <div className="min-w-0 flex-1">
                      <div className="text-[11px] text-slate-200 font-bold truncate">{w.title}</div>
                      <div className="text-[9px] text-indigo-400 font-bold">{w.price ? `$${w.price.toFixed(2)}` : '$--'}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Explain Panel */}
          {selectedProduct && (
            <div className="bg-slate-800/90 border border-indigo-500/20 rounded-2xl p-4 space-y-3 relative overflow-hidden">
              <div className="absolute top-0 right-0 w-24 h-24 bg-indigo-500/5 rounded-full blur-2xl"></div>
              <div className="flex items-center justify-between border-b border-slate-700/50 pb-2">
                <span className="text-xs font-bold text-indigo-300 flex items-center gap-1">
                  <Cpu size={14} />
                  底层得分可解释面板
                </span>
                <button 
                  onClick={() => setSelectedProduct(null)} 
                  className="text-slate-500 hover:text-slate-350 cursor-pointer"
                >
                  <EyeOff size={14} />
                </button>
              </div>

              <div className="text-left space-y-2">
                <div className="text-[11px] text-slate-200 font-extrabold line-clamp-1">{selectedProduct.title}</div>
                {explaining ? (
                  <div className="py-4 text-center">
                    <div className="w-4 h-4 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin inline-block"></div>
                    <span className="text-[10px] text-slate-400 ml-2">正在归因推理分数...</span>
                  </div>
                ) : (
                  <pre className="text-[10px] leading-relaxed text-slate-300 bg-slate-950/60 p-2.5 rounded-xl border border-slate-700/80 font-mono whitespace-pre-wrap">
                    {explanation}
                  </pre>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
