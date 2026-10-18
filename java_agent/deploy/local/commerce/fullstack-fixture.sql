-- 仅新建隔离环境使用。
INSERT INTO checkout_offer(sku_id,item_id,item_title,unit_price) VALUES ('it-sku','it-item','完整交易联调商品',3000);
INSERT INTO sku_stock(sku_id,item_id,available_stock) VALUES ('it-sku','it-item',200);
INSERT INTO inventory_stock_baseline(sku_id,opening_total) VALUES ('it-sku',200);
CREATE TABLE amazon_reviews_base(user_id VARCHAR(128),parent_asin VARCHAR(128),rating INT,event_time DATETIME,review_key VARCHAR(128));
INSERT INTO amazon_reviews_base VALUES ('it-profile','it-item',5,CURRENT_TIMESTAMP,'it-review');
