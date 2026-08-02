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
  rating: number | null;
  store: string | null;
  features: string[];
  description: string | null;
  imageUrl: string | null;
  badges: string[];
  summary: string | null;
}
