import { beforeEach, describe, expect, it, vi } from 'vitest';

const { postJson } = vi.hoisted(() => ({ postJson: vi.fn() }));

vi.mock('./shared', () => ({
  isMockMode: () => false,
  mockDelay: vi.fn(),
  postJson,
}));

import { fetchCatalogItems } from './catalogClient';
import { mergeRecommendAndCatalog } from '../utils/displayViewModel';

describe('Catalog batch client contract', () => {
  beforeEach(() => {
    postJson.mockReset();
  });

  it('sends the Gateway Catalog path and snake_case payload, then maps card fields', async () => {
    postJson.mockResolvedValue([
      {
        item_id: 'B002',
        title: 'Catalog Headphones',
        category: 'Audio',
        brand: 'Acme',
        store_name: 'Catalog Store',
        price: 248,
        image_url: 'https://example.test/headphones.png',
        summary: 'Catalog summary',
      },
    ]);

    await expect(fetchCatalogItems(['B002'])).resolves.toEqual([
      expect.objectContaining({
        itemId: 'B002',
        store: 'Catalog Store',
        imageUrl: 'https://example.test/headphones.png',
        description: 'Catalog summary',
        brand: 'Acme',
      }),
    ]);
    expect(postJson).toHaveBeenCalledWith('/catalog/items/batch', { item_ids: ['B002'] });
  });

  it('uses Catalog card data while retaining recommendation metadata', () => {
    const [product] = mergeRecommendAndCatalog([
      {
        item_id: 'B002',
        rank: 2,
        score: 0.91,
        reason: 'Matches your need',
        source_tags: ['content_semantic'],
        display: {
          title: 'Stale title',
          category: 'Stale category',
          store: 'Stale store',
          image_url: 'https://example.test/stale.png',
        },
      },
    ], [
      {
        itemId: 'B002',
        title: 'Catalog Headphones',
        category: 'Audio',
        brand: 'Acme',
        price: 248,
        rating: null,
        store: 'Catalog Store',
        features: [],
        description: 'Catalog summary',
        imageUrl: 'https://example.test/headphones.png',
        badges: [],
        summary: 'Catalog summary',
      },
    ]);

    expect(product).toMatchObject({
      itemId: 'B002',
      title: 'Catalog Headphones',
      category: 'Audio',
      store: 'Catalog Store',
      imageUrl: 'https://example.test/headphones.png',
      description: 'Catalog summary',
      rank: 2,
      score: 0.91,
      reason: 'Matches your need',
      badges: ['content_semantic'],
    });
  });
});
