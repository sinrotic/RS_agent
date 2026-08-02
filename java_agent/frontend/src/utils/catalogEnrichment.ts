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
    return {
      products: mergeRecommendAndCatalog(items, catalogItems),
      catalogAvailable: true,
    };
  } catch {
    return {
      products: mergeRecommendAndCatalog(items),
      catalogAvailable: false,
    };
  }
}
