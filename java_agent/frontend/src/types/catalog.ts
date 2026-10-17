export interface CatalogItemCardVO {
  item_id: string;
  title: string | null;
  category: string | null;
  brand: string | null;
  store_name: string | null;
  price: number | null;
  image_url: string | null;
  summary: string | null;
}

export interface CatalogItem {
  itemId: string;
  title: string | null;
  category: string | null;
  brand: string | null;
  price: number | null;
  store: string | null;
  description: string | null;
  imageUrl: string | null;
  summary: string | null;
}

export interface CatalogItemDetail {
  itemId: string;
  sourceItemId: string | null;
  title: string | null;
  category: string | null;
  categoryPath: string | null;
  brand: string | null;
  storeName: string | null;
  price: number | null;
  imageUrl: string | null;
  summary: string | null;
  description: string | null;
  attributes: Record<string, string>;
}

export interface CatalogItemWire {
  item_id: string;
  title: string | null;
  category: string | null;
  brand: string | null;
  store_name: string | null;
  price: number | null;
  image_url: string | null;
  summary: string | null;
}

export interface CatalogItemDetailWire extends CatalogItemWire {
  source_item_id: string | null;
  category_path: string | null;
  description: string | null;
  attributes: Record<string, string> | null;
}
