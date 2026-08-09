import { beforeEach, describe, expect, it, vi } from 'vitest';

const { fetchCatalogItems } = vi.hoisted(() => ({ fetchCatalogItems: vi.fn() }));

vi.mock('../api/catalogClient', () => ({ fetchCatalogItems }));

import { enrichRecommendedProducts } from './catalogEnrichment';

const recommendation = {
  item_id: 'B002',
  rank: 2,
  score: 0.91,
  reason: 'Matches your need',
  source_tags: ['content_semantic'],
  display: {
    title: 'Recommended title',
    category: 'Audio',
    store: 'Recommended Store',
    image_url: 'https://example.test/recommend.png',
  },
};

describe('Catalog enrichment', () => {
  beforeEach(() => {
    fetchCatalogItems.mockReset();
  });

  it('enriches recommendation items with Catalog cards', async () => {
    fetchCatalogItems.mockResolvedValue([
      {
        itemId: 'B002',
        title: 'Catalog title',
        category: 'Audio',
        brand: 'Acme',
        price: 248,
        rating: null,
        store: 'Catalog Store',
        features: [],
        description: 'Catalog summary',
        imageUrl: 'https://example.test/catalog.png',
        badges: [],
        summary: 'Catalog summary',
      },
    ]);

    await expect(enrichRecommendedProducts([recommendation])).resolves.toMatchObject({
      catalogAvailable: true,
      products: [{ title: 'Catalog title', rank: 2, score: 0.91 }],
    });
    expect(fetchCatalogItems).toHaveBeenCalledWith(['B002']);
  });

  it('keeps recommendation display data when Catalog is unavailable', async () => {
    fetchCatalogItems.mockRejectedValue(new Error('Catalog unavailable'));

    await expect(enrichRecommendedProducts([recommendation])).resolves.toMatchObject({
      catalogAvailable: false,
      products: [{
        title: 'Recommended title',
        rank: 2,
        score: 0.91,
        reason: 'Matches your need',
        badges: ['content_semantic'],
      }],
    });
  });

  it('drops unknown ids when Catalog returns only part of the requested items', async () => {
    fetchCatalogItems.mockResolvedValue([{
      itemId: 'B002',
      title: 'Known item',
      category: 'Audio',
      brand: 'Acme',
      price: null,
      rating: null,
      store: null,
      features: [],
      description: null,
      imageUrl: null,
      badges: [],
      summary: null,
    }]);

    const unknown = { ...recommendation, item_id: 'B404' };
    await expect(enrichRecommendedProducts([unknown, recommendation])).resolves.toMatchObject({
      catalogAvailable: true,
      products: [{ itemId: 'B002', title: 'Known item' }],
    });
  });
});
