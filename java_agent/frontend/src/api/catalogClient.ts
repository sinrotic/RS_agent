import { CatalogItem, CatalogItemDetail, CatalogItemDetailWire, CatalogItemWire } from '../types/catalog';
import { getJson, isMockMode, postJson, mockDelay } from './shared';
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
        store: found?.display.store || 'Generic Store',
        description: '这是系统内置的高清音质与精美工业设计商品。通过推荐算法与画像模型匹配，自动分发给意向人群。',
        imageUrl: found?.display.image_url || null,
        summary: '系统精选的数码配件，融合最新的声音信号传导与工业人体工学设计，提供超乎想象的音效体验。'
      };
    });
  }

  // Real request to Java Endpoint: rs-service-catalog -> POST /api/catalog/items/batch
  const response = await postJson<CatalogItemWire[]>('/catalog/items/batch', catalogBatchRequest(itemIds));
  return response.map(mapCatalogItem);
}

export function catalogBatchRequest(itemIds: string[]): { item_ids: string[] } {
  return { item_ids: itemIds };
}

export async function fetchCatalogItemDetail(itemId: string): Promise<CatalogItemDetail> {
  if (isMockMode()) {
    await mockDelay(180);
    const found = MOCK_RECOMMEND_ITEMS.find(item => item.item_id === itemId);
    return {
      itemId,
      sourceItemId: itemId,
      title: found?.display.title || `Mock Item ${itemId}`,
      category: found?.display.category || 'Electronics / Gadgets',
      categoryPath: found?.display.category || 'Electronics / Gadgets',
      brand: 'JavaAgent Select',
      storeName: found?.display.store || 'Generic Store',
      price: itemId === 'B08HEKJZ5S' ? 248.0 : itemId === 'B09DFTCL5K' ? 129.95 : 79.99,
      imageUrl: found?.display.image_url || null,
      summary: 'System-selected digital accessory with a carefully tuned recommendation profile.',
      description: 'A detailed product view powered by the catalog service. Review the product attributes and recommendation context before deciding what to explore next.',
      attributes: {
        'Recommendation source': found?.source_tags?.join(', ') || 'personalized feed',
        Compatibility: 'Universal',
        'Recommendation context': found?.display.category || 'personalized feed'
      }
    };
  }

  const response = await getJson<CatalogItemDetailWire>(`/catalog/items/${encodeURIComponent(itemId)}`);
  return mapCatalogItemDetail(response);
}

export function mapCatalogItem(item: CatalogItemWire): CatalogItem {
  return {
    itemId: item.item_id,
    title: item.title,
    category: item.category,
    brand: item.brand,
    price: item.price,
    store: item.store_name,
    description: item.summary,
    imageUrl: item.image_url,
    summary: item.summary,
  };
}
export function mapCatalogItemDetail(item: CatalogItemDetailWire): CatalogItemDetail {
  return {
    itemId: item.item_id,
    sourceItemId: item.source_item_id,
    title: item.title,
    category: item.category,
    categoryPath: item.category_path,
    brand: item.brand,
    storeName: item.store_name,
    price: item.price,
    imageUrl: item.image_url,
    summary: item.summary,
    description: item.description,
    attributes: item.attributes || {},
  };
}
