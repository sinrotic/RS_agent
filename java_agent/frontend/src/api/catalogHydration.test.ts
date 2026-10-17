import { beforeEach, describe, expect, it, vi } from 'vitest';

const { fetchCatalogItems } = vi.hoisted(() => ({ fetchCatalogItems: vi.fn() }));

vi.mock('./catalogClient', () => ({ fetchCatalogItems }));

import { hydrateRecommendedProducts } from './catalogHydration';

const recommendation = (itemId: string) => ({
  item_id: itemId,
  rank: 1,
  score: 0.91,
  reason: 'Matches the current need',
  source_tags: ['content_semantic'],
  display: {
    title: `Recommendation ${itemId}`,
    category: 'Audio',
    store: 'Recommendation Store',
    image_url: '',
  },
});

describe('Catalog hydration', () => {
  beforeEach(() => {
    fetchCatalogItems.mockReset();
  });

  it('does not fabricate cards when Catalog returns no matching rows', async () => {
    fetchCatalogItems.mockResolvedValue([]);

    await expect(hydrateRecommendedProducts([recommendation('B404')])).resolves.toMatchObject({
      catalogUnavailable: false,
      products: [],
    });
  });

  it('keeps the recommended order while dropping ids missing from Catalog', async () => {
    fetchCatalogItems.mockResolvedValue([{
      itemId: 'B002',
      title: 'Catalog Headphones',
      category: 'Audio',
      brand: 'Acme',
      price: 248,
      store: 'Catalog Store',
      description: 'Catalog summary',
      imageUrl: null,
      summary: 'Catalog summary',
    }]);

    await expect(hydrateRecommendedProducts([
      recommendation('B404'),
      recommendation('B002'),
    ])).resolves.toMatchObject({
      catalogUnavailable: false,
      products: [
        { itemId: 'B002', title: 'Catalog Headphones' },
      ],
    });
  });
});
