import { RecommendItemVO, HomeRecommendVO } from '../types/recommend';
import { CatalogItem } from '../types/catalog';

export interface DisplayProduct {
  itemId: string;
  title: string;
  category: string;
  store: string;
  imageUrl: string | null;
  price: number | null;
  rating: number | null;
  features: string[];
  description: string | null;
  badges: string[];
  reason: string;
  score: number;
  rank: number;
}

export interface FeedbackContext {
  actionType: string;
  label: string;
  itemId?: string;
}

export interface RecommendationGroup {
  id: string;
  title: string;
  description: string;
  items: DisplayProduct[];
}

export interface DisplayViewModel {
  intentSummary: {
    title: string;
    subtitle: string;
    chips: string[];
  };
  groups: RecommendationGroup[];
  referenceContext?: {
    label: string;
    itemId?: string;
  };
}

const GENERIC_WORDS = new Set([
  'for', 'and', 'the', 'this', 'that', 'with', 'want', 'need', 'some', 'item', 'items', 'product', 'products',
  'recommend', 'prefer', 'looking', 'please', 'show', 'give', '找', '推荐', '商品', '东西', '一些', '一个',
]);

const BADGE_LABELS: Record<string, string> = {
  collaborative_filtering: '协同过滤',
  category_hot: '热门商品',
  content_semantic: '语义匹配',
  user_interest_cluster: '画像偏好',
  cold_fallback: '兜底推荐',
  popularity_score: '人气推荐'
};

export function mergeRecommendAndCatalog(
  items: RecommendItemVO[],
  catalog: CatalogItem[] = []
): DisplayProduct[] {
  return items.map(item => {
    const detail = catalog.find(c => c.itemId === item.item_id);
    return {
      itemId: item.item_id,
      title: detail?.title || item.display?.title || `商品 ${item.item_id}`,
      category: detail?.category || item.display?.category || '数码配件',
      store: detail?.store || item.display?.store || '智能商城自营',
      imageUrl: detail?.imageUrl || item.display?.image_url || null,
      price: detail?.price ?? null,
      rating: detail?.rating ?? null,
      features: detail?.features || [],
      description: detail?.description || detail?.summary || null,
      badges: item.source_tags || detail?.badges || [],
      reason: item.reason || '契合您的个性化诉求',
      score: item.score,
      rank: item.rank
    };
  });
}

export function buildDisplayViewModel(
  recommendVO: HomeRecommendVO | null,
  products: DisplayProduct[],
  latestUserMessage?: string,
  feedbackContext?: FeedbackContext | null,
  assistantMessage?: string
): DisplayViewModel {
  const safeProducts = Array.isArray(products) ? products : [];
  return {
    intentSummary: buildIntentSummary(recommendVO, safeProducts, latestUserMessage, assistantMessage),
    groups: buildRecommendationGroups(safeProducts),
    referenceContext: buildReferenceContext(feedbackContext),
  };
}

export function userFacingBadgeLabel(badge: string): string | null {
  const normalized = String(badge || '').trim();
  if (!normalized || normalized === 'missing_image') return null;
  return BADGE_LABELS[normalized] || normalized.replace(/_/g, ' ');
}

function buildIntentSummary(
  _recommendVO: HomeRecommendVO | null,
  products: DisplayProduct[],
  latestUserMessage?: string,
  assistantMessage?: string
) {
  const query = cleanUserNeed(latestUserMessage || '');
  const categories = unique(products.map((item) => item.category).filter(Boolean)).slice(0, 3);
  const featureTerms = unique(products.flatMap((item) => item.features || []).map(compactTerm).filter(Boolean)).slice(0, 3);
  const badgeTerms = unique(products.flatMap((item) => item.badges || []).map((badge) => userFacingBadgeLabel(badge)).filter(Boolean) as string[]).slice(0, 2);
  const userTerms = extractUserTerms(query).slice(0, 3);
  const chips = unique([...userTerms, ...categories, ...featureTerms, ...badgeTerms]).slice(0, 8);

  return {
    title: query ? `我理解你想找：${query}` : '根据当前偏好为您整理推荐',
    subtitle: compactSentence(assistantMessage || '') || '下面按品类与匹配度为您整理的推荐结果。',
    chips,
  };
}

function buildRecommendationGroups(products: DisplayProduct[]): RecommendationGroup[] {
  if (products.length === 0) return [];
  const categories = unique(products.map((item) => item.category || '').filter(Boolean));
  if (categories.length > 1) {
    return categories.map((category) => ({
      id: category,
      title: `推荐方向：${category}`,
      description: '这一组商品属于相近品类，便于你横向比较后继续反馈。',
      items: products.filter((item) => item.category === category),
    }));
  }

  const primary = products.filter((item) => Boolean(item.price || item.rating));
  const fallback = products.filter((item) => !primary.includes(item));
  if (primary.length > 0 && fallback.length > 0) {
    return [
      {
        id: 'primary',
        title: categories[0] ? `为您主推：${categories[0]}` : '为您主推',
        description: '这些商品信息更完整，适合作为本轮优先比较对象。',
        items: primary,
      },
      {
        id: 'alternatives',
        title: '备选推荐',
        description: '这些商品可作为补充选择，您可以继续给出偏好反馈。',
        items: fallback,
      },
    ];
  }

  return [{
    id: categories[0] || 'recommended',
    title: categories[0] ? `个性化推荐：${categories[0]}` : '为您推荐',
    description: '你可以点赞、表示不感兴趣或追问推荐原因，继续优化模型。',
    items: products,
  }];
}

function buildReferenceContext(feedbackContext?: FeedbackContext | null) {
  if (!feedbackContext) return undefined;
  const itemSuffix = feedbackContext.itemId ? ` ${feedbackContext.itemId}` : '';
  if (feedbackContext.actionType === 'like' && feedbackContext.itemId) {
    return { label: `已记录您点赞的商品${itemSuffix}，推荐引擎正在找相似特征的产品。`, itemId: feedbackContext.itemId };
  }
  if (feedbackContext.actionType === 'dislike' && feedbackContext.itemId) {
    return { label: `已屏蔽商品${itemSuffix}，推荐引擎已调低此特征的权重。`, itemId: feedbackContext.itemId };
  }
  if (feedbackContext.actionType === 'why' && feedbackContext.itemId) {
    return { label: `展示商品${itemSuffix}的推荐得分来源。您可以追问以获得进一步解释。`, itemId: feedbackContext.itemId };
  }
  if (feedbackContext.actionType === 'show_different') {
    return { label: '已切换为多样化探索模式，展现更多差异化商品。' };
  }
  return undefined;
}

function cleanUserNeed(value: string): string {
  const cleaned = value
    .replace(/^\[Action Submitted\]:/i, '')
    .replace(/item_id=\S+/gi, '')
    .replace(/\s+/g, ' ')
    .trim();
  return cleaned.length > 52 ? `${cleaned.slice(0, 52)}…` : cleaned;
}

function extractUserTerms(value: string): string[] {
  const english = value
    .toLowerCase()
    .match(/[a-z0-9][a-z0-9_-]{2,}/g) || [];
  const chinese = value.match(/[一-鿿]{2,}/g) || [];
  return unique([...english.filter((word) => !GENERIC_WORDS.has(word)), ...chinese]).slice(0, 4);
}

function compactTerm(value: string): string {
  const trimmed = String(value || '').replace(/\s+/g, ' ').trim();
  if (!trimmed) return '';
  return trimmed.length > 22 ? `${trimmed.slice(0, 22)}…` : trimmed;
}

function compactSentence(value: string): string {
  const trimmed = String(value || '').replace(/\s+/g, ' ').trim();
  if (!trimmed) return '';
  return trimmed.length > 88 ? `${trimmed.slice(0, 88)}…` : trimmed;
}

function unique<T>(values: T[]): T[] {
  return Array.from(new Set(values));
}
