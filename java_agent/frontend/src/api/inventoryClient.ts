import { InventoryAvailability, InventoryAvailabilityWire } from '../types/inventory';
import { ApiError, getJson, isMockMode, mockDelay } from './shared';

export async function fetchInventoryAvailability(itemId: string): Promise<InventoryAvailability | null> {
  if (isMockMode()) {
    await mockDelay(100);
    return null;
  }

  try {
    const response = await getJson<InventoryAvailabilityWire>(
      `/inventory/items/${encodeURIComponent(itemId)}/availability`,
    );
    return mapInventoryAvailability(response);
  } catch (reason) {
    if (reason instanceof ApiError && reason.status === 404) {
      return null;
    }
    throw reason;
  }
}

export function mapInventoryAvailability(value: InventoryAvailabilityWire): InventoryAvailability {
  return {
    itemId: value.item_id,
    skuCount: value.sku_count,
    availableStock: value.available_stock,
    available: value.available,
  };
}
