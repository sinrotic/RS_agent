import { describe, expect, it } from 'vitest';
import { agentChatRequest, mapAgentChatResponse } from './agentClient';
import { catalogBatchRequest, mapCatalogItem, mapCatalogItemDetail } from './catalogClient';
import { homeFeedbackCursor, homeRecommendRefreshRequest, homeRecommendRequest } from './recommendClient';
import { mapInventoryAvailability } from './inventoryClient';

describe('HTTP wire contract mapping', () => {
  it('keeps different, similar, and current-batch refresh intents distinct', () => {
    const nextCursor = 'feed:delivery-3';
    const tokens = [
      nextCursor,
      homeFeedbackCursor('like', nextCursor, 'delivery-3', 'feed:delivery-2'),
      homeFeedbackCursor('dislike', nextCursor, 'delivery-3', 'feed:delivery-2'),
    ];
    expect(tokens.map(cursor => homeRecommendRefreshRequest({
      sessionId: 'session-1', cursor, refreshAction: 'legacy-action',
    }).refresh_token)).toEqual([
      'feed:delivery-3', 'similar:delivery-3', 'rerank:delivery-3',
    ]);
  });

  it('keeps feedback on the current batch when the server uses legacy pagination', () => {
    expect(homeFeedbackCursor('like', 'item-18', 'delivery-3', 'item-12')).toBe('item-12');
    expect(homeFeedbackCursor('dislike', 'item-18', 'delivery-3', 'item-12')).toBe('item-12');
  });

  it('maps inventory availability from snake_case', () => {
    expect(mapInventoryAvailability({
      item_id: 'item-1',
      sku_count: 2,
      available_stock: 7,
      available: true,
    })).toEqual({
      itemId: 'item-1',
      skuCount: 2,
      availableStock: 7,
      available: true,
    });
  });

  it('builds snake_case requests for Catalog, recommendation, and Agent services', () => {
    expect(catalogBatchRequest(['B001'])).toEqual({ item_ids: ['B001'] });
    expect(homeRecommendRequest({ sessionId: 'session-1', limit: 6 })).toMatchObject({
      session_id: 'session-1',
      page_size: 6,
    });
    expect(agentChatRequest('session-1', 'user-1', '通勤耳机')).toEqual({
      session_id: 'session-1',
      profile_user_id: 'user-1',
      user_message: '通勤耳机',
      limit: 5,
      context: { scene: 'agent_chat' },
    });
  });

  it('maps Catalog card snake_case fields into the display model', () => {
    expect(mapCatalogItem({
      item_id: 'B001',
      title: 'Backpack',
      category: 'Bags',
      brand: 'RoadMate',
      store_name: 'RoadMate Store',
      price: 49.9,
      image_url: 'https://example.com/item.jpg',
      summary: 'Daily backpack',
    })).toMatchObject({
      itemId: 'B001',
      store: 'RoadMate Store',
      imageUrl: 'https://example.com/item.jpg',
      description: 'Daily backpack',
    });
  });

  it('maps Catalog detail snake_case fields and normalizes null attributes', () => {
    expect(mapCatalogItemDetail({
      item_id: 'B001',
      source_item_id: 'SRC-1',
      title: 'Backpack',
      category: 'Bags',
      category_path: 'Bags > Travel',
      brand: 'RoadMate',
      store_name: 'RoadMate Store',
      price: 49.9,
      image_url: null,
      summary: null,
      description: 'Water-resistant',
      attributes: null,
    })).toMatchObject({
      itemId: 'B001',
      sourceItemId: 'SRC-1',
      categoryPath: 'Bags > Travel',
      storeName: 'RoadMate Store',
      attributes: {},
    });
  });

  it('maps Agent recommended_items without inventing request or turn ids', () => {
    expect(mapAgentChatResponse({
      request_id: 'agent-1',
      session_id: 'session-1',
      profile_user_id: 'user-1',
      card_set_id: 'rec-1',
      turn_index: 2,
      assistant_message: 'Here are the matches.',
      recommended_items: [{
        item_id: 'B001',
        title: 'Backpack',
        category: 'Bags',
        score: 0.91,
        reason: 'Matches commute needs',
      }],
      tool_calls: [],
    })).toEqual({
      requestId: 'agent-1',
      sessionId: 'session-1',
      profileUserId: 'user-1',
      cardSetId: 'rec-1',
      turnIndex: 2,
      assistantMessage: 'Here are the matches.',
      items: [{
        item_id: 'B001',
        rank: 1,
        score: 0.91,
        reason: 'Matches commute needs',
        source_tags: [],
        display: {
          title: 'Backpack',
          category: 'Bags',
          store: '',
          image_url: '',
        },
      }],
      toolCalls: [],
      degradationReasons: [],
    });
  });
});
