package com.sinrotic.rs.order.service.seckill;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

import java.util.HashMap;
import java.util.Map;

@Component
@ConfigurationProperties(prefix = "rs.seckill")
public class SeckillActivityProperties {

    private Map<String, Activity> activities = new HashMap<>();

    public Map<String, Activity> getActivities() {
        return activities;
    }

    public void setActivities(Map<String, Activity> activities) {
        this.activities = activities == null ? new HashMap<>() : activities;
    }

    public static class Activity {

        private Map<String, Item> items = new HashMap<>();

        public Map<String, Item> getItems() {
            return items;
        }

        public void setItems(Map<String, Item> items) {
            this.items = items == null ? new HashMap<>() : items;
        }
    }

    public static class Item {

        private Map<String, Sku> skus = new HashMap<>();

        public Map<String, Sku> getSkus() {
            return skus;
        }

        public void setSkus(Map<String, Sku> skus) {
            this.skus = skus == null ? new HashMap<>() : skus;
        }
    }

    public static class Sku {

        private String itemTitle;
        private Long unitPrice;

        public String getItemTitle() {
            return itemTitle;
        }

        public void setItemTitle(String itemTitle) {
            this.itemTitle = itemTitle;
        }

        public Long getUnitPrice() {
            return unitPrice;
        }

        public void setUnitPrice(Long unitPrice) {
            this.unitPrice = unitPrice;
        }
    }
}
