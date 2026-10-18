import { getJson, postJson } from './shared';

export interface Offer { skuId: string; itemId: string; itemTitle: string; unitPrice: number; }
export interface Campaign {
  campaignId: string; title: string; itemId: string | null; remainingQuantity: number;
  minimumAmount: number; discountAmount: number; expiresAt: string;
}
export interface Coupon {
  couponId: string; campaignId: string; status: string; title: string; itemId: string | null;
  minimumAmount: number; discountAmount: number; expiresAt: string;
}
export interface CheckoutRequest {
  requestId: string; itemId: string; skuId: string; quantity: number; couponId: string | null;
  sessionId?: string | null; recommendRequestId?: string | null;
}
export interface CheckoutOrder {
  orderId: number; status: string; phase: string; itemId: string; skuId: string; itemTitle: string;
  quantity: number; originalAmount: number; discountAmount: number; totalAmount: number;
  couponId: string | null; expiresAt: string; failureReason: string | null;
}
export const listOffers = (itemId: string) => getJson<Offer[]>(`/checkout/offers?itemId=${encodeURIComponent(itemId)}`);
export const listCampaigns = (itemId: string) => getJson<Campaign[]>(`/promotions/campaigns?itemId=${encodeURIComponent(itemId)}`);
export const listCoupons = () => getJson<Coupon[]>('/promotions/coupons');
export const claimCoupon = (campaignId: string, requestId: string) =>
  postJson<Coupon>(`/promotions/campaigns/${encodeURIComponent(campaignId)}/claim`, { requestId });
export const listCheckoutOrders = () => getJson<CheckoutOrder[]>('/checkout/orders');
export const createCheckoutOrder = (request: CheckoutRequest) => postJson<CheckoutOrder>('/checkout/orders', request);
export const cancelCheckoutOrder = (id: number) => postJson<CheckoutOrder>(`/checkout/orders/${id}/cancel`, {});
export type MockPaymentScenario = 'SUCCESS' | 'DECLINED' | 'TIMEOUT_BEFORE_PAYMENT' | 'RESPONSE_LOST';
export const mockPayCheckoutOrder = (id: number, scenario: MockPaymentScenario = 'SUCCESS') =>
  postJson<CheckoutOrder>(`/checkout/orders/${id}/mock-pay`, { scenario });
export const checkoutCapabilities = () => getJson<{ mockPaymentEnabled: boolean }>('/checkout/capabilities');
export interface SeckillResult { requestId: string; status: string; orderId: number | null; }
export interface SeckillActivity {
  activityId: string; itemId: string; skuId: string; itemTitle: string; unitPrice: number;
  totalQuantity: number; remainingQuantity: number; startsAt: string; endsAt: string; serverTime: string;
  status: string; participation: SeckillResult | null;
  inventoryMode?: 'ALLOCATED' | 'SHARED_LEGACY';
}
export interface SeckillRequest { requestId: string; itemId: string; skuId: string; quantity: 1; }
export const listSeckillActivities = (itemId: string) => getJson<SeckillActivity[]>(`/seckill/activities?itemId=${encodeURIComponent(itemId)}`);
export const getSeckillActivity = (id: string) => getJson<SeckillActivity>(`/seckill/activities/${encodeURIComponent(id)}`);
export const submitSeckill = (activityId: string, request: SeckillRequest) =>
  postJson<SeckillResult>(`/seckill/activities/${encodeURIComponent(activityId)}/submit`, request);
export const getSeckillResult = (requestId: string) => getJson<SeckillResult>(`/seckill/requests/${encodeURIComponent(requestId)}`);
export const getCheckoutOrder = (id: number) => getJson<CheckoutOrder>(`/checkout/orders/${id}`);
export interface CommercePage<T> { items: T[]; nextCursor: string | null; }
export interface RefundRequest { requestId: string; reason: string; scenario: MockPaymentScenario; }
export interface Refund { refundId: string; orderId: number; amount: number; status: string; phase: string; reason: string; lastError: string | null; }
export const listOrderPage = (beforeId?: string) => getJson<CommercePage<CheckoutOrder>>(`/checkout/orders/page?limit=20${beforeId ? `&beforeId=${encodeURIComponent(beforeId)}` : ''}`);
export const listCouponPage = (afterId?: string) => getJson<CommercePage<Coupon>>(`/promotions/coupons/page?limit=20${afterId ? `&afterId=${encodeURIComponent(afterId)}` : ''}`);
export const requestOrderRefund = (id: number, request: RefundRequest) => postJson<Refund>(`/checkout/orders/${id}/refunds`, request);
export const getOrderRefund = (id: number) => getJson<Refund>(`/checkout/orders/${id}/refund`);
