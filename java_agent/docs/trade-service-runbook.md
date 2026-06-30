# Trade Service Runbook

## Start Order

1. Apply the trade schema before starting the services:

   ```bash
   mysql -uroot -proot rs_agent < java_agent/sql/rs_service_trade_schema.sql
   ```

   Or from an interactive MySQL shell:

   ```sql
   USE rs_agent;
   SOURCE java_agent/sql/rs_service_trade_schema.sql;
   ```

2. Start the infrastructure dependencies:

   - Nacos on `127.0.0.1:8848`
   - MySQL with database `rs_agent`
   - Redis on `127.0.0.1:6379`
   - Kafka on `localhost:9092`

3. Start `rs-service-inventory` on port `8092`.
4. Start `rs-service-order` on port `8091`.
5. Start `rs-service-payment` on port `8093`.
6. Start `rs-service-seckill` on port `8094`.
7. Start `rs-api-gateway` on port `8080`.

Public app traffic should go through the gateway, for example
`http://localhost:8080/api/orders`, `http://localhost:8080/api/payments/prepay`,
`http://localhost:8080/callback/payments/mock`, and
`http://localhost:8080/api/seckill/activities/act-1/submit`.

Before running the smoke requests, log in through the gateway auth API, for
example `/api/auth/login`, and copy the returned access token. All gateway
`/api/**` curl examples below require `Authorization: Bearer <access-token>`.
The mock provider callback at `/callback/payments/mock` is provider-facing and
does not use this Authorization header.

Inventory endpoints are internal service-to-service APIs only. The order service
calls `rs.inventory.base-url`, which defaults to `http://localhost:8092`, and then
uses `/internal/inventory/lock`, `/internal/inventory/confirm-deduct`, and
`/internal/inventory/release`. Do not expose `/internal/inventory/**` through the
gateway.

## Normal Order Smoke

1. Seed one stock row:

   ```sql
   INSERT INTO sku_stock (sku_id, item_id, available_stock, locked_stock, sold_stock)
   VALUES ('sku-1', 'item-1', 10, 0, 0)
   ON DUPLICATE KEY UPDATE
       item_id = VALUES(item_id),
       available_stock = 10,
       locked_stock = 0,
       sold_stock = 0;
   ```

2. Create an order through the gateway:

   ```bash
   curl -X POST http://localhost:8080/api/orders \
     -H "Authorization: Bearer <access-token>" \
     -H "Content-Type: application/json" \
     -d '{"requestId":"req-normal-1","accountId":1,"profileUserId":"profile-1","sessionId":"session-1","recommendRequestId":"rec-1","itemId":"item-1","skuId":"sku-1","itemTitle":"Smoke Item","quantity":1,"unitPrice":100}'
   ```

3. Verify `orders.status = 'WAITING_PAYMENT'` for `request_id = 'req-normal-1'`.
4. Verify `sku_stock.available_stock = 9` and `sku_stock.locked_stock = 1` for
   `sku_id = 'sku-1'`.
5. Create a mock payment prepay row, replacing `<orderId>` with the created order
   id:

   ```bash
   curl -X POST http://localhost:8080/api/payments/prepay \
     -H "Authorization: Bearer <access-token>" \
     -H "Content-Type: application/json" \
     -d '{"orderId":<orderId>,"accountId":1,"amount":100,"provider":"mock"}'
   ```

6. Simulate the provider callback. The mock provider requires provider `mock` and
   signature `mock-signature`:

   ```bash
   curl -X POST http://localhost:8080/callback/payments/mock \
     -H "Content-Type: application/json" \
     -d '{"providerTransactionId":"mock-tx-normal-1","orderId":<orderId>,"amount":100,"signature":"mock-signature","rawPayload":"{\"event\":\"paid\",\"tx\":\"mock-tx-normal-1\"}"}'
   ```

7. Verify `orders.status = 'PAID'`.
8. Verify `sku_stock.locked_stock = 0` and `sku_stock.sold_stock = 1`.

## Smoke Reruns

The smoke payloads above intentionally use readable fixed ids. Reusing the same
`requestId`, `providerTransactionId`, or Redis user key will hit idempotency and
duplicate-submit guards on reruns. Prefer replacing these values with unique ids
for each run, for example `req-normal-<timestamp>`, `req-seckill-<timestamp>`,
and `mock-tx-normal-<timestamp>`.

If you need to rerun with the fixed sample ids, clear only the smoke data you
created. At minimum, remove the seckill duplicate-submit key:

```bash
redis-cli DEL seckill:user:act-1:1
```

For MySQL cleanup, first identify the smoke `order_id` values from `orders` by
their `request_id`, and identify payment callback rows by
`providerTransactionId`. Then clean related rows in dependency order, for
example `payment_callbacks`, `payment_orders`, `stock_logs`, `order_items`, and
finally `orders`. The current schema does not define foreign keys, but still
delete by the exact smoke `order_id` and `request_id` values to avoid removing
unrelated audit or payment rows.

## Seckill Smoke

Seckill is only the entry layer: it performs Redis pre-deduct and enqueues a Kafka
message on `seckill-order-create`. The final MySQL stock lock, order creation,
payment callback, and inventory confirmation still reuse the normal order,
inventory, and payment path.

1. Seed the same MySQL stock row used by the final normal order flow:

   ```sql
   INSERT INTO sku_stock (sku_id, item_id, available_stock, locked_stock, sold_stock)
   VALUES ('sku-1', 'item-1', 10, 0, 0)
   ON DUPLICATE KEY UPDATE
       item_id = VALUES(item_id),
       available_stock = 10,
       locked_stock = 0,
       sold_stock = 0;
   ```

2. Configure the order service with the seckill item snapshot before starting it.
   Without this config, the Kafka consumer fails in a controlled way and does not
   write an order with an incorrect amount.

   ```yaml
   rs:
     seckill:
       activities:
         act-1:
           items:
             item-1:
               skus:
                 sku-1:
                   item-title: Smoke Seckill Item
                   unit-price: 100
   ```

3. Set Redis pre-deduct stock:

   ```bash
   redis-cli SET seckill:stock:act-1:sku-1 5
   ```

4. Submit a seckill request through the gateway:

   ```bash
   curl -X POST http://localhost:8080/api/seckill/activities/act-1/submit \
     -H "Authorization: Bearer <access-token>" \
     -H "Content-Type: application/json" \
     -d '{"requestId":"req-seckill-1","accountId":1,"itemId":"item-1","skuId":"sku-1","quantity":1}'
   ```

5. Verify the response status is `PROCESSING`.
6. Verify Redis pre-deducted `seckill:stock:act-1:sku-1` from `5` to `4` and wrote
   `seckill:user:act-1:1`.
7. Verify Kafka delivered the message to `rs-service-order` and created a
   `WAITING_PAYMENT` order with `request_id = 'req-seckill-1'`.
8. Finish the seckill order through the same payment flow as a normal order:
   call `/api/payments/prepay` with provider `mock` and
   `Authorization: Bearer <access-token>`, then call `/callback/payments/mock`
   with signature `mock-signature`, and verify the order becomes `PAID` with the
   final MySQL inventory confirmation.
