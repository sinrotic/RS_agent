import { CatalogItem, CatalogItemCardVO } from '../types/catalog';
import { isMockMode, postJson, mockDelay } from './shared';
import { MOCK_RECOMMEND_ITEMS } from './recommendClient';

export async function fetchCatalogItems(itemIds: string[]): Promise<CatalogItem[]> {
  if (isMockMode()) {
    await mockDelay(200);
    return itemIds.map(id => {
      const found = MOCK_RECOMMEND_ITEMS.find(item => item.item_id === id);
      return {
        itemId: id,
        title: found?.display.title || `Mock Item ${id}`,
        category: found?.display.category || 'Electronics / Gadgets',
        brand: null,
        price: found ? (id === 'B08HEKJZ5S' ? 248.0 : id === 'B09DFTCL5K' ? 129.95 : 79.99) : 99.99,
        rating: 4.8,
        store: found?.display.store || 'Generic Store',
        features: [
          '主动降噪 / Active Noise Canceling',
          '超长电池寿命 / Long Battery Life',
          '无线蓝牙 5.0 适配 / Wireless Bluetooth 5.0'
        ],
        description: '这是系统内置的高清音质与精美工业设计商品。通过推荐算法与画像模型匹配，自动分发给意向人群。',
        imageUrl: found?.display.image_url || null,
        badges: found?.source_tags || ['collaborative_filtering'],
        summary: '系统精选的数码配件，融合最新的声音信号传导与工业人体工学设计，提供超乎想象的音效体验。'
      };
    });
  }

  const cards = await postJson<CatalogItemCardVO[]>('/catalog/items/batch', {
    item_ids: itemIds,
  });
  return cards.map(mapCatalogItemCard);
}

export function mapCatalogItemCard(card: CatalogItemCardVO): CatalogItem {
  return {
    itemId: card.item_id,
    title: card.title,
    category: card.category,
    brand: card.brand,
    price: card.price,
    rating: null,
    store: card.store_name,
    features: [],
    description: card.summary,
    imageUrl: card.image_url,
    badges: [],
    summary: card.summary,
  };
}
