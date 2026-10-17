import { RecommendItemVO } from '../types/recommend';
import { DisplayProduct, mergeRecommendAndCatalog } from '../utils/displayViewModel';
import { fetchCatalogItems } from './catalogClient';

export interface CatalogHydrationResult {
  products: DisplayProduct[];
  catalogUnavailable: boolean;
}

export async function hydrateRecommendedProducts(items: RecommendItemVO[]): Promise<CatalogHydrationResult> {
  if (items.length === 0) {
    return { products: [], catalogUnavailable: false };
  }
  try {
    const catalog = await fetchCatalogItems(items.map(item => item.item_id));
    return {
      products: mergeRecommendAndCatalog(items, catalog, true),
      catalogUnavailable: false,
    };
  } catch {
    return {
      products: mergeRecommendAndCatalog(items),
      catalogUnavailable: true,
    };
  }
}
