import { fetchCatalogItems } from '../api/catalogClient';
import { RecommendItemVO } from '../types/recommend';
import { DisplayProduct, mergeRecommendAndCatalog } from './displayViewModel';

export interface CatalogEnrichmentResult {
  products: DisplayProduct[];
  catalogAvailable: boolean;
}

export async function enrichRecommendedProducts(
  items: RecommendItemVO[]
): Promise<CatalogEnrichmentResult> {
  try {
    const catalogItems = await fetchCatalogItems(items.map((item) => item.item_id));
    const catalogItemIds = new Set(catalogItems.map((item) => item.itemId));
    const knownItems = items.filter((item) => catalogItemIds.has(item.item_id));
    return {
      products: mergeRecommendAndCatalog(knownItems, catalogItems),
      catalogAvailable: true,
    };
  } catch {
    return {
      products: mergeRecommendAndCatalog(items),
      catalogAvailable: false,
    };
  }
}
