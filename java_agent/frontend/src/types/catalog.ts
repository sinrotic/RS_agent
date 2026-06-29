export interface CatalogItem {
  itemId: string;
  title: string | null;
  category: string | null;
  price: number | null;
  rating: number | null;
  store: string | null;
  features: string[];
  description: string | null;
  imageUrl: string | null;
  badges: string[];
  summary: string | null;
}
