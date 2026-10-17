import { useState, useEffect, useRef } from 'react';
import { RefreshCw, Heart, Compass, Cpu, EyeOff } from 'lucide-react';
import { homeFeedbackCursor, recommendHome, refreshHome } from '../api/recommendClient';
import { recordEvent, waitForFeedbackApplied } from '../api/interactionClient';
import { startSession } from '../api/sessionClient';
import { buildDisplayViewModel, DisplayProduct, DisplayViewModel } from '../utils/displayViewModel';
import { GroupedRecommendationGrid } from '../components/GroupedRecommendationGrid';
import { ProductFeedbackAction } from '../components/ProductCard';
import { RecommendationIntentSummary } from '../components/RecommendationIntentSummary';
import { ApiError, getStoredProfileUserId, isMockMode } from '../api/shared';
import { hydrateRecommendedProducts } from '../api/catalogHydration';
import { useVisibleRecommendationExposure } from '../hooks/useVisibleRecommendationExposure';

interface MallHomeProps {
  onOpenProduct: (product: DisplayProduct) => void;
}

export function MallHome({ onOpenProduct }: MallHomeProps) {
  const [profileUserId, setProfileUserId] = useState<string>('');
  const [sessionId, setSessionId] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);
  const [status, setStatus] = useState<string>('Initializing Mall Feed...');
  const [products, setProducts] = useState<DisplayProduct[]>([]);
  const [viewModel, setViewModel] = useState<DisplayViewModel | null>(null);
  const [feedError, setFeedError] = useState<string>('');
  const [lastRequestId, setLastRequestId] = useState<string>('');
  const [pageStartCursor, setPageStartCursor] = useState('');
  const [nextCursor, setNextCursor] = useState('');
  const [hasMore, setHasMore] = useState(true);
  const [degraded, setDegraded] = useState(false);
  const [explanationProduct, setExplanationProduct] = useState<DisplayProduct | null>(null);

  // Wishlist state
  const [wishlist, setWishlist] = useState<DisplayProduct[]>([]);

  // Obs Details
  const [explanation, setExplanation] = useState<string>('');
  const [explaining, setExplaining] = useState<boolean>(false);
  const exposureRootRef = useRef<HTMLDivElement>(null);
  const initializeStartedRef = useRef(false);

  useVisibleRecommendationExposure(exposureRootRef, lastRequestId, sessionId, products);

  const recoverEndedSession = (error: unknown): boolean => {
    if (!(error instanceof ApiError) || error.status !== 410) return false;
    setSessionId('');
    setLastRequestId('');
    setProducts([]);
    setViewModel(null);
    setPageStartCursor('');
    setNextCursor('');
    setHasMore(true);
    setExplanationProduct(null);
    setFeedError('推荐会话已结束，请重新加载以创建新会话。');
    setStatus('推荐会话已结束。');
    return true;
  };

  // Read stored user on mount
  useEffect(() => {
    if (initializeStartedRef.current) return;
    initializeStartedRef.current = true;
    const stored = getStoredProfileUserId() || 'guest_user';
    setProfileUserId(stored);
    handleInitialize(stored);
  }, []);

  const handleInitialize = async (userId: string) => {
    setLoading(true);
    setFeedError('');
    setStatus('正在创建推荐会话并生成初始个性化商品流...');
    try {
      // 1. Start session
      const sessionRes = await startSession(userId);
      setSessionId(sessionRes.sessionId);

      // 2. Fetch recommend items
      const recRes = await recommendHome({
        sessionId: sessionRes.sessionId,
        scene: 'home',
        limit: 6,
        debug: true
      });
      setLastRequestId(recRes.request_id);
      setDegraded(recRes.recommendation_mode === 'degraded');

      // 3. Enrich details from catalog service
      const hydration = await hydrateRecommendedProducts(recRes.items);
      const mergedProducts = hydration.products;
      setPageStartCursor('');
      setNextCursor(recRes.next_cursor);
      setHasMore(recRes.has_more);
      setProducts(mergedProducts);

      // 5. Build viewModel
      const vm = buildDisplayViewModel(recRes, mergedProducts, '', null, recRes.recommendation_mode === 'discovery' ? '先探索一些商品，喜欢后会为你寻找相似选择：' : '根据你的兴趣，为你推荐以下商品：');
      setViewModel(vm);

      setStatus(hydration.catalogUnavailable ? '推荐已加载，商品详情暂不可用。' : '个性化推荐加载成功！');
    } catch (e: any) {
      console.error(e);
      const message = e instanceof Error ? e.message : '未知错误';
      setFeedError(`初始化推荐失败：${message}`);
      setStatus(`初始化推荐失败: ${message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleRefresh = async () => {
    if (!sessionId || loading || (!hasMore && !isMockMode())) return;
    setLoading(true);
    setStatus('正在寻找不同方向的推荐商品...');
    try {
      const recRes = await refreshHome({
        sessionId,
        scene: 'home',
        limit: 6,
        cursor: nextCursor,
        refreshAction: 'rerecall_pool500'
      });
      setLastRequestId(recRes.request_id);
      setDegraded(recRes.recommendation_mode === 'degraded');

      const hydration = await hydrateRecommendedProducts(recRes.items);
      const mergedProducts = hydration.products;
      setPageStartCursor(nextCursor);
      setNextCursor(recRes.next_cursor);
      setHasMore(recRes.has_more);
      setProducts(mergedProducts);

      const vm = buildDisplayViewModel(recRes, mergedProducts, '换个方向', { actionType: 'show_different', label: '换一批' }, '换个方向看看，为你挑选了以下商品：');
      setViewModel(vm);

      setStatus(hydration.catalogUnavailable ? '推荐已刷新，商品详情暂不可用。' : '首页推荐流刷新成功！');
    } catch (e: any) {
      if (!recoverEndedSession(e)) setStatus(`刷新失败: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleFeedback = async (actionType: ProductFeedbackAction, itemId: string) => {
    if (!sessionId || loading) return;

    if (!lastRequestId) {
      setStatus('服务端尚未返回 request_id，无法提交反馈。');
      return;
    }

    if (actionType === 'why') {
      try {
        await recordEvent({
          request_id: lastRequestId,
          session_id: sessionId,
          item_id: itemId,
          event_type: 'why',
          event_value: 0,
          occurred_at: Date.now()
        });
        const item = products.find(p => p.itemId === itemId);
        if (item) {
          setExplanationProduct(item);
          setExplanation(item.reason || '推荐服务暂未返回该商品的解释。');
          setExplaining(false);
        }
      } catch (e: any) {
        if (!recoverEndedSession(e)) setStatus(`推荐理由事件记录失败: ${e.message}`);
      }
      return;
    }

    setLoading(true);
    const label = actionType === 'like' ? '喜欢，找相似' : '不感兴趣';
    setStatus(`已捕获交互信号 [${label}]，正在更新推荐兴趣模型...`);

    try {
      // 1. Record event
      let ack = await recordEvent({
        request_id: lastRequestId,
        session_id: sessionId,
        item_id: itemId,
        event_type: actionType,
        event_value: actionType === 'like' ? 1.0 : -1.0,
        occurred_at: Date.now()
      });

      if (ack.application_status === 'PENDING') {
        setStatus('反馈已保存，在线偏好正在同步...');
        ack = await waitForFeedbackApplied(ack.feedback_id);
        if (ack.application_status !== 'APPLIED') {
          setStatus('反馈已保存，推荐仍在等待在线偏好同步。');
          return;
        }
      }
      if (!ack.accepted) {
        throw new Error('推荐服务拒绝了本次反馈');
      }

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
        scene: 'home',
        limit: 6,
        cursor: homeFeedbackCursor(actionType, nextCursor, lastRequestId, pageStartCursor),
        refreshAction: actionType === 'like' ? 'find_similar' : 'rerank_existing'
      });
      setLastRequestId(recRes.request_id);
      setDegraded(recRes.recommendation_mode === 'degraded');

      const hydration = await hydrateRecommendedProducts(recRes.items);
      const mergedProducts = hydration.products;
      setNextCursor(recRes.next_cursor);
      setHasMore(recRes.has_more);
      setProducts(mergedProducts);

      const vm = buildDisplayViewModel(
        recRes,
        mergedProducts,
        actionType === 'like' ? `喜欢商品 ${itemId}` : `踩商品 ${itemId}`,
        { actionType, label, itemId },
        '推荐引擎已自动完成排序重构，适配您的最新意向：'
      );
      setViewModel(vm);

      const applied = recRes.preference_version >= ack.preference_version
        && recRes.applied_feedback_event_ids.includes(ack.feedback_id);
      setStatus(applied ? '推荐已根据反馈更新。' : '反馈已保存，推荐结果仍在等待偏好版本同步。');
    } catch (e: any) {
      if (!recoverEndedSession(e)) setStatus(`反馈提交失败: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div ref={exposureRootRef} className="flex-1 flex flex-col gap-6 text-slate-100 overflow-y-auto min-h-0 text-left">
      {/* Top Banner */}
      <div className="relative rounded-2xl bg-linear-to-r from-indigo-600 via-indigo-900 to-slate-950 p-6 md:p-8 shadow-xl overflow-hidden shrink-0">
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
              disabled={loading || !sessionId || (!hasMore && !isMockMode())}
              title="换个方向，看看不同的商品"
              className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white transition-all font-bold rounded-xl px-5 py-3 text-xs flex items-center gap-1.5 shadow-lg shadow-indigo-600/25 cursor-pointer"
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              {!hasMore && !isMockMode() ? '已浏览完当前商品' : '换一批推荐'}
            </button>
          </div>
        </div>
      </div>

      {/* Main Grid: Left for Feed / Right for cart&detail */}
      {degraded && <div role="status" className="rounded-xl border border-amber-500/30 bg-amber-950/20 px-4 py-3 text-sm text-amber-200">
        部分推荐能力暂时不可用，当前展示可用的商品推荐。你的反馈会继续保存。
      </div>}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 items-start">
        {/* Recommend Feed */}
        <div className="lg:col-span-3 space-y-6">
          {viewModel && <RecommendationIntentSummary viewModel={viewModel} />}

          {loading ? (
            <div className="py-20 flex flex-col items-center justify-center gap-3">
              <div className="w-10 h-10 border-4 border-indigo-500/30 border-t-indigo-500 rounded-full animate-spin"></div>
              <div className="text-xs text-indigo-400 font-bold tracking-widest uppercase">{status}</div>
            </div>
          ) : feedError ? (
            <div role="alert" className="rounded-2xl border border-rose-500/30 bg-rose-950/30 px-6 py-10 text-center">
              <div className="font-bold text-rose-200">推荐内容暂时没有加载出来</div>
              <div className="mt-2 text-xs text-rose-300/80">{feedError}</div>
              <button
                type="button"
                onClick={() => handleInitialize(profileUserId || 'guest_user')}
                className="mt-5 rounded-xl bg-rose-500/20 px-4 py-2 text-xs font-bold text-rose-100 hover:bg-rose-500/30"
              >
                重新加载
              </button>
            </div>
          ) : viewModel && viewModel.groups.length === 0 ? (
            <div role="status" className="rounded-2xl border border-slate-700 bg-slate-900/40 px-6 py-10 text-center text-sm text-slate-300">
              {hasMore ? '当前这一批没有可展示的商品，请继续换一批。' : '已浏览完当前可用商品。'}
            </div>
          ) : (
            viewModel && (
              <GroupedRecommendationGrid
                groups={viewModel.groups}
                onFeedback={handleFeedback}
                onOpen={product => onOpenProduct({ ...product, sessionId, recommendRequestId: lastRequestId })}
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
          {explanationProduct && (
            <div className="bg-slate-800/90 border border-indigo-500/20 rounded-2xl p-4 space-y-3 relative overflow-hidden">
              <div className="absolute top-0 right-0 w-24 h-24 bg-indigo-500/5 rounded-full blur-2xl"></div>
              <div className="flex items-center justify-between border-b border-slate-700/50 pb-2">
                <span className="text-xs font-bold text-indigo-300 flex items-center gap-1">
                  <Cpu size={14} />
                  推荐理由
                </span>
                <button 
                  onClick={() => setExplanationProduct(null)}
                  className="text-slate-500 hover:text-slate-350 cursor-pointer"
                >
                  <EyeOff size={14} />
                </button>
              </div>

              <div className="text-left space-y-2">
                <div className="text-[11px] text-slate-200 font-extrabold line-clamp-1">{explanationProduct.title}</div>
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
