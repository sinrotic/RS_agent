import { DisplayItem, DisplayResponse } from '../types';

export interface FeedbackContext {
  actionType: string;
  label: string;
  itemId?: string;
}

export interface RecommendationGroup {
  id: string;
  title: string;
  description: string;
  items: DisplayItem[];
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
  blended_signal: '综合推荐',
  matches_feedback: '符合反馈',
  diverse_match: '拓展选择',
  fallback: '备选方向',
};

export function buildDisplayViewModel(
  display: DisplayResponse,
  items: DisplayItem[],
  latestUserMessage?: string,
  feedbackContext?: FeedbackContext | null,
): DisplayViewModel {
  const safeItems = Array.isArray(items) ? items : [];
  return {
    intentSummary: buildIntentSummary(display, safeItems, latestUserMessage),
    groups: buildRecommendationGroups(safeItems),
    referenceContext: buildReferenceContext(feedbackContext),
  };
}

export function userFacingBadgeLabel(badge: string): string | null {
  const normalized = String(badge || '').trim();
  if (!normalized || normalized === 'missing_image') return null;
  return BADGE_LABELS[normalized] || normalized.replace(/_/g, ' ');
}

export function recommendationReason(item: DisplayItem): string {
  if (item.summary?.trim()) return item.summary.trim();
  const features = (item.features || []).filter(Boolean).slice(0, 2);
  if (features.length > 0) return `匹配点：${features.join('、')}`;
  if (item.description?.trim()) return item.description.trim();
  return '可以通过反馈继续细化这个推荐方向。';
}

function buildIntentSummary(display: DisplayResponse, items: DisplayItem[], latestUserMessage?: string) {
  const query = cleanUserNeed(latestUserMessage || '');
  const categories = unique(items.map((item) => item.category).filter(Boolean) as string[]).slice(0, 3);
  const featureTerms = unique(items.flatMap((item) => item.features || []).map(compactTerm).filter(Boolean)).slice(0, 3);
  const badgeTerms = unique(items.flatMap((item) => item.badges || []).map((badge) => userFacingBadgeLabel(badge)).filter(Boolean) as string[]).slice(0, 2);
  const userTerms = extractUserTerms(query).slice(0, 3);
  const chips = unique([...userTerms, ...categories, ...featureTerms, ...badgeTerms]).slice(0, 8);

  return {
    title: query ? `我理解你想找：${query}` : '根据当前偏好为你整理推荐',
    subtitle: compactSentence(display.assistant_message) || '下面按方向整理了可继续反馈的推荐结果。',
    chips,
  };
}

function buildRecommendationGroups(items: DisplayItem[]): RecommendationGroup[] {
  if (items.length === 0) return [];
  const categories = unique(items.map((item) => item.category || '').filter(Boolean));
  if (categories.length > 1) {
    return categories.map((category) => ({
      id: category,
      title: `主推方向：${category}`,
      description: '这一组商品属于相近品类，便于你横向比较后继续反馈。',
      items: items.filter((item) => item.category === category),
    }));
  }

  const primary = items.filter((item) => Boolean(item.summary || item.image_url || item.rating));
  const fallback = items.filter((item) => !primary.includes(item));
  if (primary.length > 0 && fallback.length > 0) {
    return [
      {
        id: 'primary',
        title: categories[0] ? `最推荐先看：${categories[0]}` : '最推荐先看',
        description: '这些商品信息更完整，适合作为本轮优先比较对象。',
        items: primary,
      },
      {
        id: 'alternatives',
        title: '备选方向',
        description: '这些商品可作为补充选择，如果方向不对可以继续反馈。',
        items: fallback,
      },
    ];
  }

  return [{
    id: categories[0] || 'recommended',
    title: categories[0] ? `为你推荐：${categories[0]}` : '为你推荐',
    description: '你可以点赞、说明不感兴趣，或追问为什么推荐来继续调整。',
    items,
  }];
}

function buildReferenceContext(feedbackContext?: FeedbackContext | null) {
  if (!feedbackContext) return undefined;
  const itemSuffix = feedbackContext.itemId ? ` ${feedbackContext.itemId}` : '';
  if (feedbackContext.actionType === 'like' && feedbackContext.itemId) {
    return { label: `已参考你喜欢的商品${itemSuffix}，优先找相近但更贴合当前需求的选择。`, itemId: feedbackContext.itemId };
  }
  if (feedbackContext.actionType === 'dislike' && feedbackContext.itemId) {
    return { label: `已记录你不感兴趣的商品${itemSuffix}，下一轮会尽量避开类似方向。`, itemId: feedbackContext.itemId };
  }
  if (feedbackContext.actionType === 'why' && feedbackContext.itemId) {
    return { label: `正在围绕商品${itemSuffix}解释推荐原因，你也可以继续要求更便宜或更相似的替代。`, itemId: feedbackContext.itemId };
  }
  if (feedbackContext.actionType === 'show_different') {
    return { label: '已切换到不同方向，下面会更强调新的探索选择。' };
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
