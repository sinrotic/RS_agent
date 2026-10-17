-- 仅用于新建隔离数据库，绝不复用生产 SKU。
INSERT INTO checkout_offer(sku_id,item_id,item_title,unit_price) VALUES ('it-sku','it-item','隔离库存测试商品',3000);
INSERT INTO sku_stock(sku_id,item_id,available_stock) VALUES ('it-sku','it-item',30);
