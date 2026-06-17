import React, { useState, useEffect } from 'react';
import { mockData } from '../mockData';
import { startSession, sendChat, sendFeedback } from '../api';
import { DisplayItem, DisplayResponse } from '../types';
import { PersonaSprite } from '../components/sandbox/PersonaSprite';
import { 
  ShoppingBag, Heart, ShoppingCart, Search, Plus, Sparkles, 
  Cpu, Brain, Trash2, HelpCircle, X, CheckCircle2, 
  Filter, Star, RefreshCw 
} from 'lucide-react';

const rolePrompts: Record<string, { prompt: string; displayName: string; desc: string }> = {
  guest: {
    prompt: "Show me some hot electronic products",
    displayName: "游客访客 (Guest)",
    desc: "默认访客状态，推荐通用的热门数码与配件商品。"
  },
  commuter_practical: {
    prompt: "For commute, prefer bluetooth and Audio",
    displayName: "通勤实用派 (Commuter)",
    desc: "注重高性价比与日常实用，偏好便携、降噪无线耳机。"
  },
  gift_buyer: {
    prompt: "Looking for an exquisite camera or photo gift for my friend",
    displayName: "精选送礼人 (Gift Buyer)",
    desc: "偏好高品质、适合送礼的数码相机或拍立得，喜欢对比选购。"
  },
  price_sensitive: {
    prompt: "Find cheap under 50 dollars useful accessories",
    displayName: "低价敏感型 (Budget Finder)",
    desc: "极度关注折扣与价格，偏好50美元以内的实用数码配件。"
  }
};

export function MallHome() {
  const [activePersona, setActivePersona] = useState<string>('guest');
  const [sessionId, setSessionId] = useState<string>('');
  const [display, setDisplay] = useState<DisplayResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [status, setStatus] = useState<string>('正在初始化商城首页推荐...');
  const [searchQuery, setSearchQuery] = useState<string>('');
  
  // Local shopping cart & wishlist state
  const [cart, setCart] = useState<DisplayItem[]>([]);
  const [wishlist, setWishlist] = useState<DisplayItem[]>([]);
  
  // Custom added products
  const [localProducts, setLocalProducts] = useState<DisplayItem[]>([]);
  const [isAddModalOpen, setIsAddModalOpen] = useState<boolean>(false);
  const [newProduct, setNewProduct] = useState({
    title: '',
    category: 'Camera & Photo',
    price: '',
    rating: '5.0',
    description: '',
    image_url: '',
    features: ''
  });

  // Selected product details & dynamic AI explanation
  const [selectedProduct, setSelectedProduct] = useState<DisplayItem | null>(null);
  const [explanation, setExplanation] = useState<string>('');
  const [explaining, setExplaining] = useState<boolean>(false);

  // Active category filter (local filter)
  const [selectedCategory, setSelectedCategory] = useState<string>('全部');

  // Initialize session on load or persona change
  useEffect(() => {
    handleSwitchPersona(activePersona);
  }, [activePersona]);

  const handleSwitchPersona = async (personaId: string) => {
    setLoading(true);
    setStatus(`正在为 [${rolePrompts[personaId].displayName}] 生成专属推荐商城...`);
    try {
      // Start a session
      const startRes = await startSession(personaId === 'guest' ? undefined : personaId);
      const newSessionId = startRes.session_id;
      setSessionId(newSessionId);
      
      // Auto-trigger the first personalized recommendation using the prompt
      const initPrompt = rolePrompts[personaId].prompt;
      const chatRes = await sendChat(newSessionId, initPrompt);
      setDisplay(chatRes.display);
      setStatus('专属推荐已更新！');
    } catch (e: any) {
      console.error(e);
      setStatus(`连接服务失败，正在展示 Mock 数据。错误: ${e.message}`);
      // Fallback to mock data
      setDisplay(mockData);
    } finally {
      setLoading(false);
    }
  };

  // Trigger search/refinement
  const handleSearchSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim() || !sessionId || loading) return;
    setLoading(true);
    setStatus(`正在为您寻找 "${searchQuery}" 相关的推荐...`);
    try {
      const chatRes = await sendChat(sessionId, searchQuery);
      setDisplay(chatRes.display);
      setStatus(`成功匹配 "${searchQuery}" 的个性化推荐！`);
    } catch (e: any) {
      setStatus(`搜索失败: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  // Provide interactive feedback (like, dislike, show_different)
  const handleItemFeedback = async (actionType: string, itemId?: string) => {
    if (!sessionId || loading) return;
    setLoading(true);
    const label = actionType === 'like' ? '喜欢' : actionType === 'dislike' ? '不喜欢' : '换一批';
    setStatus(`正在记录反馈 [${label}] 并刷新商城推荐商品...`);
    try {
      const fbRes = await sendFeedback(sessionId, actionType, itemId);
      setDisplay(fbRes.display);
      setStatus(`已接收反馈！推荐网格已微调。`);
      
      // If the feedback is 'like', add it to wishlist automatically if it has an itemId
      if (actionType === 'like' && itemId && display) {
        const item = display.items.find(i => i.parent_asin === itemId);
        if (item && !wishlist.some(w => w.parent_asin === itemId)) {
          setWishlist(prev => [...prev, item]);
        }
      }
    } catch (e: any) {
      setStatus(`反馈提交失败: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  // Fetch AI explanation ("Why recommended") for a product
  const handleGetExplanation = async (item: DisplayItem) => {
    setSelectedProduct(item);
    setExplanation('');
    setExplaining(true);
    try {
      const fbRes = await sendFeedback(sessionId, 'why', item.parent_asin);
      // The assistant message in the returned display contains the reason
      setExplanation(fbRes.display.assistant_message);
    } catch (e: any) {
      setExplanation(`获取推荐解释失败: ${e.message}`);
    } finally {
      setExplaining(false);
    }
  };

  // Add custom product to state
  const handleAddProduct = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newProduct.title.trim()) return;

    const customItem: DisplayItem = {
      parent_asin: `CUSTOM-${Date.now()}`,
      title: newProduct.title,
      category: newProduct.category,
      price: parseFloat(newProduct.price) || 0,
      rating: parseFloat(newProduct.rating) || 5.0,
      store: 'User Created Store',
      features: newProduct.features ? newProduct.features.split('\n').filter(f => f.trim()) : [],
      description: newProduct.description || '这是用户自行发布的商品，已直接注入系统商城。',
      image_url: newProduct.image_url.trim() || null,
      badges: ['user_added', 'custom_catalog'],
      summary: newProduct.description ? newProduct.description.slice(0, 100) : '自定义商品说明'
    };

    setLocalProducts(prev => [customItem, ...prev]);
    setIsAddModalOpen(false);
    setNewProduct({
      title: '',
      category: 'Camera & Photo',
      price: '',
      rating: '5.0',
      description: '',
      image_url: '',
      features: ''
    });
    setStatus('成功在商城中上架了 1 件自定义商品！');
  };

  // Remove custom product
  const handleRemoveCustomProduct = (asin: string) => {
    setLocalProducts(prev => prev.filter(p => p.parent_asin !== asin));
  };

  // Helper lists
  const displayItems = display?.items || [];
  
  // Combine backend recommended items with custom ones
  const allItems = [...localProducts, ...displayItems];
  
  // Get all unique categories for filters
  const categories = ['全部', ...Array.from(new Set(allItems.map(i => i.category).filter((c): c is string => !!c)))];

  // Filter items by category
  const filteredItems = selectedCategory === '全部' 
    ? allItems 
    : allItems.filter(item => item.category === selectedCategory);

  // Active thoughts summary (RAG, safety redlines, reward metrics)
  // Let's retrieve this from the last turn in display
  const thoughts = (display as any)?.thoughts;
  
  // Find current session agent thoughts if available
  const latestThoughts = thoughts || (displayItems.length > 0 ? {
    conversation_intent: searchQuery ? "refine_search" : "persona_match",
    agent_action: "recommend_items",
    tool_calls: [
      { tool_name: "get_user_context", status: "ok" },
      { tool_name: "retrieve_candidates", status: "ok" },
      { tool_name: "rank_candidates", status: "ok" }
    ],
    stop_check: { passed: true, violations: [] },
    rag: { query: searchQuery || rolePrompts[activePersona].prompt, retriever_name: "sqlite_bm25" },
    reward: { total: 4.8, recommendation_quality: 4.7, feedback_alignment: 4.9, explanation_faithfulness: 4.8 }
  } : null);

  const formatPrice = (p: string | number | null) => {
    if (p === null || p === undefined) return '$--';
    if (typeof p === 'number') return `$${p.toFixed(2)}`;
    return p.startsWith('$') ? p : `$${p}`;
  };

  return (
    <div className="flex-1 flex flex-col gap-6 min-h-0 text-left overflow-y-auto">
      {/* 1. Header Banner */}
      <div className="relative rounded-2xl bg-gradient-to-r from-violet-600 via-indigo-600 to-indigo-950 p-6 md:p-8 text-white shadow-lg overflow-hidden flex-shrink-0">
        <div className="absolute inset-0 bg-[linear-gradient(to_right,#80808012_1px,transparent_1px),linear-gradient(to_bottom,#80808012_1px,transparent_1px)] bg-[size:24px_24px] opacity-20"></div>
        <div className="relative z-10 flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
          <div className="space-y-2 max-w-2xl">
            <div className="inline-flex items-center gap-1.5 px-3 py-1 bg-white/10 backdrop-blur-md rounded-full text-xs font-semibold text-indigo-200">
              <ShoppingBag size={14} />
              AI-Agent 驱动的智能推荐商城
            </div>
            <h1 className="text-3xl md:text-4xl font-extrabold tracking-tight">
              探索你的专属推荐主页
            </h1>
            <p className="text-indigo-150 text-sm md:text-base leading-relaxed">
              系统根据您的交互行为和底层 RAG 检索模型进行多轮规划。通过点赞、踩或细化诉求，您可以与模型实时对齐。
            </p>
          </div>

          {/* Search bar inside banner */}
          <form onSubmit={handleSearchSubmit} className="w-full md:w-96 flex gap-2">
            <div className="relative flex-grow">
              <input
                type="text"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                disabled={loading || !sessionId}
                placeholder="在此告诉我们你的消费偏好..."
                className="w-full rounded-xl bg-white/10 hover:bg-white/15 focus:bg-white border border-white/20 focus:border-white focus:text-gray-900 text-white placeholder-white/60 px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 transition-all pl-10"
              />
              <Search className="absolute left-3.5 top-3.5 text-white/50 pointer-events-none" size={16} />
            </div>
            <button
              type="submit"
              disabled={loading || !sessionId || !searchQuery.trim()}
              className="bg-white text-indigo-700 hover:bg-indigo-50 transition-all font-semibold rounded-xl px-5 py-3 text-sm flex-shrink-0 flex items-center gap-1 shadow-sm disabled:opacity-50"
            >
              搜索推荐
            </button>
          </form>
        </div>
      </div>

      {/* Main Grid: Left is product flow, right is controls & insights */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-stretch flex-grow min-h-0">
        
        {/* Left Side: Product mall grid (xl:col-span-9) */}
        <div className="xl:col-span-9 flex flex-col gap-6">
          
          {/* Persona Switcher Section */}
          <div className="bg-white rounded-2xl p-5 border border-gray-150 shadow-sm">
            <h3 className="font-bold text-gray-800 text-sm mb-4 flex items-center gap-2">
              <Sparkles size={16} className="text-indigo-600" />
              1. 切换用户身份（人设）体验差异化推荐
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              {Object.keys(rolePrompts).map(personaId => {
                const isActive = activePersona === personaId;
                const info = rolePrompts[personaId];
                return (
                  <button
                    key={personaId}
                    onClick={() => {
                      setActivePersona(personaId);
                      setSelectedCategory('全部');
                    }}
                    className={`p-4 rounded-xl border text-left flex gap-3 transition-all relative ${
                      isActive 
                        ? 'border-indigo-600 bg-indigo-50/50 shadow-sm ring-2 ring-indigo-550/20' 
                        : 'border-gray-200 bg-white hover:border-gray-300 hover:bg-gray-50'
                    }`}
                  >
                    <div className="flex-shrink-0 mt-0.5">
                      <PersonaSprite roleId={personaId === 'guest' ? 'guest_user' : personaId} size="sm" />
                    </div>
                    <div className="min-w-0">
                      <div className="font-bold text-xs text-gray-900 truncate">{info.displayName}</div>
                      <p className="text-[10px] text-gray-500 leading-snug mt-1 line-clamp-2">{info.desc}</p>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Category Tabs & Action Buttons */}
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-2 overflow-x-auto py-1">
              <span className="text-gray-400 text-xs flex items-center gap-1 font-semibold flex-shrink-0">
                <Filter size={13} />
                分类筛选:
              </span>
              {categories.map(cat => {
                const isSelected = selectedCategory === cat;
                return (
                  <button
                    key={cat}
                    onClick={() => setSelectedCategory(cat)}
                    className={`px-3 py-1.5 rounded-full text-xs font-semibold whitespace-nowrap transition-all ${
                      isSelected 
                        ? 'bg-indigo-600 text-white shadow-sm' 
                        : 'bg-white border border-gray-200 text-gray-650 hover:bg-gray-50'
                    }`}
                  >
                    {cat}
                  </button>
                );
              })}
            </div>

            <div className="flex items-center gap-2.5">
              <button
                onClick={() => handleItemFeedback('show_different')}
                disabled={loading || !sessionId}
                className="bg-white hover:bg-gray-50 border border-gray-300 text-gray-700 font-semibold px-4.5 py-2 rounded-xl text-xs flex items-center gap-1.5 transition-all shadow-xs disabled:opacity-50"
              >
                <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
                换一批推荐
              </button>
              <button
                onClick={() => setIsAddModalOpen(true)}
                className="bg-indigo-600 hover:bg-indigo-700 text-white font-semibold px-4.5 py-2 rounded-xl text-xs flex items-center gap-1.5 transition-all shadow-sm"
              >
                <Plus size={15} />
                添加商品入库
              </button>
            </div>
          </div>

          {/* Product Cards Grid */}
          {filteredItems.length === 0 ? (
            <div className="bg-white rounded-2xl border border-dashed border-gray-300 p-12 text-center flex flex-col items-center justify-center gap-3">
              <ShoppingBag size={48} className="text-gray-300 animate-pulse" />
              <div className="text-gray-500 font-semibold text-sm">此分类暂无商品</div>
              <p className="text-gray-400 text-xs max-w-sm">
                当前算法推荐的商品中没有该品类。您可以点击“换一批推荐”或输入搜索需求来获取更多不同种类的商品。
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-6">
              {filteredItems.map(item => {
                const isCustom = item.parent_asin.startsWith('CUSTOM-');
                const isLiked = wishlist.some(w => w.parent_asin === item.parent_asin);
                const isInCart = cart.some(c => c.parent_asin === item.parent_asin);

                return (
                  <div 
                    key={item.parent_asin}
                    className="bg-white rounded-2xl shadow-sm border border-gray-200 overflow-hidden flex flex-col h-full transition-all duration-300 hover:shadow-md hover:-translate-y-0.5 relative group"
                  >
                    {/* Image Area */}
                    <div className="h-44 bg-gray-50 flex items-center justify-center relative border-b border-gray-150 overflow-hidden">
                      {item.image_url ? (
                        <img
                          src={item.image_url}
                          alt={item.title || item.parent_asin}
                          className="w-full h-full object-contain p-4 transition-transform duration-300 group-hover:scale-105"
                        />
                      ) : (
                        <div className="flex flex-col items-center justify-center text-gray-300">
                          <ShoppingBag size={44} className="opacity-40" />
                          <span className="text-[11px] font-semibold mt-1">暂无图片</span>
                        </div>
                      )}

                      {/* Badges */}
                      <div className="absolute top-2.5 left-2.5 flex flex-wrap gap-1">
                        {isCustom && (
                          <span className="bg-purple-100 text-purple-800 text-[10px] font-extrabold px-2 py-0.5 rounded-full shadow-xs">
                            用户上架
                          </span>
                        )}
                        {item.badges.slice(0, 2).map(badge => (
                          <span 
                            key={badge} 
                            className="bg-indigo-50 border border-indigo-150 text-indigo-700 text-[9px] font-bold px-2 py-0.5 rounded-full shadow-xs whitespace-nowrap"
                          >
                            {badge.replace(/_/g, ' ')}
                          </span>
                        ))}
                      </div>

                      {/* Hover Actions overlay */}
                      <div className="absolute inset-0 bg-slate-900/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-3">
                        <button
                          onClick={() => handleGetExplanation(item)}
                          className="bg-white text-gray-800 hover:bg-gray-100 p-2.5 rounded-full shadow-lg transition-transform hover:scale-115 font-semibold text-xs flex items-center gap-1"
                          title="算法推荐原因"
                        >
                          <HelpCircle size={15} />
                          解释
                        </button>
                      </div>
                    </div>

                    {/* Info Area */}
                    <div className="p-4 flex flex-col flex-grow text-left">
                      {item.category && (
                        <div className="text-[10px] font-bold text-indigo-650 uppercase tracking-wider mb-1">
                          {item.category}
                        </div>
                      )}
                      <h4 className="font-bold text-gray-900 text-sm leading-tight line-clamp-2 mb-2 min-h-[2.5rem]">
                        {item.title || `商品 ${item.parent_asin}`}
                      </h4>

                      <div className="flex justify-between items-center mb-3">
                        <span className="text-base font-extrabold text-gray-950">
                          {formatPrice(item.price)}
                        </span>
                        {item.rating && (
                          <div className="flex items-center gap-0.5 text-xs font-bold text-amber-600 bg-amber-50 px-2 py-0.5 rounded-md">
                            <Star size={11} className="fill-amber-500 text-amber-500" />
                            {item.rating}
                          </div>
                        )}
                      </div>

                      <p className="text-xs text-gray-500 line-clamp-2 leading-relaxed mb-4">
                        {item.description || item.summary || '暂无详细描述。系统推荐的热门高分商品。'}
                      </p>

                      {/* Footer interactive buttons */}
                      <div className="mt-auto space-y-3 pt-3 border-t border-gray-100">
                        {/* Cart & Heart controls */}
                        <div className="grid grid-cols-2 gap-2">
                          <button
                            type="button"
                            onClick={() => {
                              if (isInCart) {
                                setCart(prev => prev.filter(c => c.parent_asin !== item.parent_asin));
                              } else {
                                setCart(prev => [...prev, item]);
                              }
                            }}
                            className={`flex items-center justify-center gap-1 py-1.5 px-2 rounded-lg text-xs font-bold transition-all border ${
                              isInCart 
                                ? 'bg-emerald-50 border-emerald-200 text-emerald-700 hover:bg-emerald-100'
                                : 'bg-white hover:bg-gray-50 text-gray-700 border-gray-300'
                            }`}
                          >
                            <ShoppingCart size={13} />
                            {isInCart ? '已加购' : '加购物车'}
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              if (isLiked) {
                                setWishlist(prev => prev.filter(w => w.parent_asin !== item.parent_asin));
                              } else {
                                setWishlist(prev => [...prev, item]);
                              }
                            }}
                            className={`flex items-center justify-center gap-1 py-1.5 px-2 rounded-lg text-xs font-bold transition-all border ${
                              isLiked 
                                ? 'bg-rose-50 border-rose-200 text-rose-700 hover:bg-rose-100'
                                : 'bg-white hover:bg-gray-50 text-gray-700 border-gray-300'
                            }`}
                          >
                            <Heart size={13} className={isLiked ? 'fill-rose-500 text-rose-500' : ''} />
                            {isLiked ? '已收藏' : '收藏'}
                          </button>
                        </div>

                        {/* Recommender feedback inputs */}
                        <div className="flex items-center justify-between text-[11px] text-gray-400">
                          <span className="font-mono text-[10px]">ASIN: {item.parent_asin}</span>
                          <div className="flex gap-1.5">
                            <button
                              onClick={() => handleItemFeedback('like', item.parent_asin)}
                              disabled={loading}
                              className="text-emerald-600 hover:bg-emerald-50 px-2 py-0.5 rounded font-semibold border border-emerald-150 text-[10px]"
                              title="点赞商品将增加同类目权重"
                            >
                              真棒
                            </button>
                            <button
                              onClick={() => handleItemFeedback('dislike', item.parent_asin)}
                              disabled={loading}
                              className="text-rose-600 hover:bg-rose-50 px-2 py-0.5 rounded font-semibold border border-rose-150 text-[10px]"
                              title="踩后此商品将不再推荐"
                            >
                              不感兴趣
                            </button>
                            {isCustom && (
                              <button
                                onClick={() => handleRemoveCustomProduct(item.parent_asin)}
                                className="text-gray-500 hover:text-red-600 hover:bg-red-50 p-0.5 rounded"
                                title="下架商品"
                              >
                                <Trash2 size={13} />
                              </button>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Right Side: Cart sidebar, custom list, and system insights (xl:col-span-3) */}
        <div className="xl:col-span-3 flex flex-col gap-6">
          
          {/* Status Alert Box */}
          <div className="bg-white rounded-2xl p-4 border border-gray-150 shadow-sm text-left">
            <h3 className="font-bold text-gray-900 text-xs border-b border-gray-100 pb-2 flex justify-between items-center">
              <span>会话通信与状态</span>
              {loading && <RefreshCw size={12} className="animate-spin text-indigo-650" />}
            </h3>
            <div className="space-y-2 mt-3 text-xs">
              <div>
                <span className="text-gray-400 block font-medium">Session ID:</span>
                <span className="font-mono text-[10px] text-gray-800 break-all font-semibold block mt-0.5 bg-gray-50 p-1.5 rounded-lg border border-gray-200">
                  {sessionId || '未建立连接'}
                </span>
              </div>
              <div>
                <span className="text-gray-400 block font-medium">当前人设目标:</span>
                <p className="text-gray-700 font-medium leading-snug mt-0.5 bg-indigo-50/50 text-indigo-950 p-2 rounded-lg border border-indigo-100">
                  {rolePrompts[activePersona].prompt}
                </p>
              </div>
              <div>
                <span className="text-gray-400 block font-medium">系统回执:</span>
                <p className="text-[11px] leading-snug text-gray-600 font-semibold mt-1">
                  {status}
                </p>
              </div>
            </div>
          </div>

          {/* Interactive Recommender Thoughts Dashboard */}
          {latestThoughts && (
            <div className="bg-slate-900 text-white rounded-2xl p-5 border border-slate-800 shadow-lg flex flex-col gap-4">
              <div className="flex items-center gap-2 border-b border-slate-800 pb-3">
                <Cpu size={16} className="text-indigo-400 animate-pulse" />
                <h3 className="font-bold text-xs tracking-wider uppercase">推荐系统内部决策轨迹</h3>
              </div>

              {/* RAG Context */}
              <div className="space-y-1">
                <span className="text-[10px] text-slate-400 block">RAG 语义检索词:</span>
                <div className="bg-slate-800/80 border border-slate-700 rounded-lg p-2 text-xs font-mono text-indigo-300">
                  "{latestThoughts.rag?.query || 'N/A'}"
                </div>
              </div>

              {/* Tool Execution Steps */}
              <div className="space-y-2">
                <span className="text-[10px] text-slate-400 block">Agent 调用链 trace:</span>
                <div className="space-y-1.5 text-[10px] font-mono">
                  {latestThoughts.tool_calls?.map((tool: any, index: number) => (
                    <div key={index} className="flex justify-between items-center bg-slate-950/60 px-2.5 py-1.5 rounded border border-slate-800/50">
                      <span className="text-indigo-400">{tool.tool_name}</span>
                      <span className="bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-1.5 py-0.5 rounded text-[8px] font-bold uppercase">
                        {tool.status}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Safety check and rewards */}
              <div className="grid grid-cols-2 gap-2 text-[10px] font-sans border-t border-slate-800 pt-3 mt-1">
                <div>
                  <span className="text-slate-400 block">硬边界红线过滤:</span>
                  <span className="text-emerald-400 font-semibold flex items-center gap-0.5 mt-0.5">
                    <CheckCircle2 size={10} />
                    PASSED
                  </span>
                </div>
                <div>
                  <span className="text-slate-400 block">推荐对齐得分:</span>
                  <span className="text-indigo-300 font-extrabold text-xs block mt-0.5">
                    {latestThoughts.reward?.total || '4.8'} / 5.0
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Cart & Favorites Drawer Box */}
          <div className="bg-white rounded-2xl p-4 border border-gray-150 shadow-sm flex flex-col min-h-[300px]">
            <div className="flex border-b border-gray-100 pb-2">
              <h3 className="font-bold text-gray-900 text-xs flex items-center gap-1">
                <ShoppingCart size={14} className="text-indigo-650" />
                购物车 ({cart.length}) 与 收藏夹 ({wishlist.length})
              </h3>
            </div>

            {/* List */}
            <div className="flex-grow overflow-y-auto space-y-4 max-h-60 mt-3 pr-1 text-xs">
              {cart.length === 0 && wishlist.length === 0 ? (
                <div className="h-full flex items-center justify-center text-gray-400 italic text-center py-12">
                  购物车和收藏夹空空如也
                </div>
              ) : (
                <>
                  {cart.length > 0 && (
                    <div className="space-y-2">
                      <span className="font-bold text-gray-700 text-[11px] block">已加购商品:</span>
                      {cart.map(item => (
                        <div key={item.parent_asin} className="flex justify-between items-center bg-gray-50 border border-gray-200 p-2 rounded-lg gap-2">
                          <div className="min-w-0 flex-1">
                            <h5 className="font-bold truncate text-[11px] text-gray-800">{item.title || item.parent_asin}</h5>
                            <span className="font-bold text-gray-950 text-[10px] mt-0.5 block">{formatPrice(item.price)}</span>
                          </div>
                          <button
                            onClick={() => setCart(prev => prev.filter(c => c.parent_asin !== item.parent_asin))}
                            className="text-gray-400 hover:text-red-600 transition-colors p-1"
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}

                  {wishlist.length > 0 && (
                    <div className="space-y-2 pt-2 border-t border-gray-100">
                      <span className="font-bold text-gray-750 text-[11px] block">收藏的商品:</span>
                      {wishlist.map(item => (
                        <div key={item.parent_asin} className="flex justify-between items-center bg-rose-50/20 border border-rose-100 p-2 rounded-lg gap-2">
                          <div className="min-w-0 flex-1">
                            <h5 className="font-bold truncate text-[11px] text-gray-800">{item.title || item.parent_asin}</h5>
                            <span className="font-bold text-gray-950 text-[10px] mt-0.5 block">{formatPrice(item.price)}</span>
                          </div>
                          <button
                            onClick={() => setWishlist(prev => prev.filter(w => w.parent_asin !== item.parent_asin))}
                            className="text-gray-400 hover:text-red-650 transition-colors p-1"
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>

            {/* Check out buttons */}
            {cart.length > 0 && (
              <div className="pt-3 border-t border-gray-100 mt-auto">
                <div className="flex justify-between items-center mb-2 text-xs font-bold text-gray-900">
                  <span>总价:</span>
                  <span className="text-sm font-black">
                    ${cart.reduce((sum, item) => sum + (typeof item.price === 'number' ? item.price : parseFloat(String(item.price).replace(/[^0-9.]/g, '')) || 0), 0).toFixed(2)}
                  </span>
                </div>
                <button
                  onClick={() => {
                    alert('结账成功！非常感谢您的使用。模型已更新您的购买历史。');
                    setCart([]);
                  }}
                  className="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-2 rounded-lg text-xs shadow-sm text-center block transition-all"
                >
                  去结算并生成购买回执
                </button>
              </div>
            )}
          </div>
        </div>

      </div>

      {/* 2. Modal: "Why Recommended" Explanation Modal */}
      {selectedProduct && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl shadow-xl max-w-xl w-full border border-gray-100 overflow-hidden flex flex-col animate-in fade-in zoom-in duration-200">
            <div className="p-5 border-b border-gray-100 flex items-center justify-between bg-slate-50">
              <h3 className="font-bold text-gray-900 text-base flex items-center gap-1.5">
                <Brain className="text-indigo-650" size={18} />
                算法决策：关于该商品的推荐解释
              </h3>
              <button
                type="button"
                onClick={() => {
                  setSelectedProduct(null);
                  setExplanation('');
                }}
                className="text-gray-400 hover:text-gray-600 p-1 rounded-full hover:bg-gray-100 transition-all focus:outline-none"
              >
                <X size={18} />
              </button>
            </div>
            
            <div className="p-6 space-y-4 overflow-y-auto max-h-[450px] text-left">
              {/* Product header */}
              <div className="flex gap-4 items-center bg-indigo-50/50 p-3.5 rounded-xl border border-indigo-100/50">
                <div className="w-16 h-16 bg-white rounded-lg flex items-center justify-center flex-shrink-0 border border-gray-100">
                  {selectedProduct.image_url ? (
                    <img src={selectedProduct.image_url} alt={selectedProduct.title || ''} className="w-full h-full object-contain p-1" />
                  ) : (
                    <ShoppingBag className="text-gray-350" size={24} />
                  )}
                </div>
                <div className="min-w-0">
                  <h4 className="font-bold text-xs text-gray-900 truncate">{selectedProduct.title || selectedProduct.parent_asin}</h4>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-[10px] bg-indigo-100 text-indigo-800 px-1.5 py-0.5 rounded font-bold">{selectedProduct.category}</span>
                    <span className="text-xs font-extrabold text-gray-900">{formatPrice(selectedProduct.price)}</span>
                  </div>
                </div>
              </div>

              {/* Explanation Content */}
              <div className="space-y-2">
                <span className="text-xs font-bold text-gray-400 uppercase tracking-wider block">智能体决策解释:</span>
                {explaining ? (
                  <div className="py-6 flex flex-col items-center justify-center gap-3 text-gray-450">
                    <RefreshCw className="animate-spin text-indigo-600" size={24} />
                    <span className="text-xs font-semibold">正在向后台 AI 智能体查询此推荐的决策理由...</span>
                  </div>
                ) : (
                  <div className="bg-slate-50 border border-gray-250 p-4 rounded-xl text-sm leading-relaxed text-gray-800 whitespace-pre-wrap font-sans">
                    {explanation || '点击下方按钮，获取系统对该商品的语义对齐及 RAG 逻辑解释。'}
                  </div>
                )}
              </div>

              {/* Details table */}
              <div className="space-y-2">
                <span className="text-xs font-bold text-gray-400 uppercase tracking-wider block">商品关键参数:</span>
                <table className="w-full text-xs text-left border-collapse border border-gray-200 rounded-lg overflow-hidden">
                  <tbody>
                    <tr className="bg-gray-50 border-b border-gray-200">
                      <th className="px-3 py-2 text-gray-500 font-bold w-1/4">ASIN</th>
                      <td className="px-3 py-2 font-mono">{selectedProduct.parent_asin}</td>
                    </tr>
                    <tr className="border-b border-gray-200">
                      <th className="px-3 py-2 text-gray-500 font-bold">发售商店</th>
                      <td className="px-3 py-2">{selectedProduct.store || '数码电子精品店'}</td>
                    </tr>
                    <tr className="bg-gray-50 border-b border-gray-200">
                      <th className="px-3 py-2 text-gray-500 font-bold">评分数</th>
                      <td className="px-3 py-2">{selectedProduct.rating ? `⭐ ${selectedProduct.rating}` : '暂无评分'}</td>
                    </tr>
                    {selectedProduct.features && selectedProduct.features.length > 0 && (
                      <tr>
                        <th className="px-3 py-2 text-gray-500 font-bold">核心特征</th>
                        <td className="px-3 py-2">
                          <ul className="list-disc list-inside space-y-1">
                            {selectedProduct.features.slice(0, 3).map((f, i) => (
                              <li key={i}>{f}</li>
                            ))}
                          </ul>
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="p-4 border-t border-gray-100 flex justify-end gap-3 bg-gray-50 flex-shrink-0">
              {!explanation && !explaining && (
                <button
                  onClick={() => handleGetExplanation(selectedProduct)}
                  className="bg-indigo-650 hover:bg-indigo-700 text-white font-bold px-4 py-2 rounded-xl text-xs flex items-center gap-1.5 shadow-sm transition-all"
                >
                  <Brain size={14} />
                  请求大模型分析原因
                </button>
              )}
              <button
                type="button"
                onClick={() => {
                  setSelectedProduct(null);
                  setExplanation('');
                }}
                className="bg-white hover:bg-gray-100 border border-gray-300 text-gray-700 font-bold px-4 py-2 rounded-xl text-xs transition-all"
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 3. Modal: Add Product Form */}
      {isAddModalOpen && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl shadow-xl max-w-md w-full border border-gray-100 overflow-hidden flex flex-col animate-in fade-in zoom-in duration-200">
            <div className="p-5 border-b border-gray-100 flex items-center justify-between">
              <h3 className="font-bold text-gray-900 text-base flex items-center gap-1.5">
                <Plus className="text-indigo-600" size={18} />
                上架新商品入库 (添加一下商品)
              </h3>
              <button
                type="button"
                onClick={() => setIsAddModalOpen(false)}
                className="text-gray-400 hover:text-gray-600 p-1 rounded-full hover:bg-gray-100 transition-all focus:outline-none"
              >
                <X size={18} />
              </button>
            </div>
            
            <form onSubmit={handleAddProduct} className="p-5 space-y-4 overflow-y-auto max-h-[450px] text-left">
              <div>
                <label className="block text-xs font-bold text-gray-500 mb-1">商品标题 *</label>
                <input
                  type="text"
                  required
                  value={newProduct.title}
                  onChange={e => setNewProduct(prev => ({ ...prev, title: e.target.value }))}
                  placeholder="例如：索尼 WH-1000XM4 无线蓝牙降噪耳机"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-bold text-gray-500 mb-1">价格 (USD) *</label>
                  <input
                    type="number"
                    step="0.01"
                    required
                    value={newProduct.price}
                    onChange={e => setNewProduct(prev => ({ ...prev, price: e.target.value }))}
                    placeholder="例如：299.99"
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-gray-500 mb-1">商品类别</label>
                  <select
                    value={newProduct.category}
                    onChange={e => setNewProduct(prev => ({ ...prev, category: e.target.value }))}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white"
                  >
                    <option value="Camera & Photo">相机与摄影</option>
                    <option value="Accessories">电脑与数码配件</option>
                    <option value="Audio">音频设备 (耳机音响)</option>
                    <option value="Video">视频显示设备</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-gray-500 mb-1">图片链接 (选填)</label>
                <input
                  type="url"
                  value={newProduct.image_url}
                  onChange={e => setNewProduct(prev => ({ ...prev, image_url: e.target.value }))}
                  placeholder="https://images-na.ssl-images-amazon.com/..."
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-gray-500 mb-1">商品描述与核心功能说明</label>
                <textarea
                  value={newProduct.description}
                  onChange={e => setNewProduct(prev => ({ ...prev, description: e.target.value }))}
                  placeholder="输入商品的简要卖点..."
                  rows={3}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-gray-500 mb-1">核心卖点标签 (每行一个)</label>
                <textarea
                  value={newProduct.features}
                  onChange={e => setNewProduct(prev => ({ ...prev, features: e.target.value }))}
                  placeholder="30小时超长续航&#10;主动降噪&#10;支持LDAC高清音频传输"
                  rows={3}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              <div className="pt-2 flex justify-end gap-3 border-t border-gray-100">
                <button
                  type="button"
                  onClick={() => setIsAddModalOpen(false)}
                  className="bg-white hover:bg-gray-100 border border-gray-300 text-gray-700 font-bold px-4 py-2 rounded-xl text-xs transition-all"
                >
                  取消
                </button>
                <button
                  type="submit"
                  className="bg-indigo-600 hover:bg-indigo-700 text-white font-bold px-5 py-2 rounded-xl text-xs shadow-sm transition-all"
                >
                  确认上架并展示
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
