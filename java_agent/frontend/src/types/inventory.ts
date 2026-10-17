export interface InventoryAvailability {
  itemId: string;
  skuCount: number;
  availableStock: number;
  available: boolean;
}

export interface InventoryAvailabilityWire {
  item_id: string;
  sku_count: number;
  available_stock: number;
  available: boolean;
}
