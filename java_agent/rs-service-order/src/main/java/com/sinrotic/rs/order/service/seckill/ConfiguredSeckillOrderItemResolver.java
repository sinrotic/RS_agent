package com.sinrotic.rs.order.service.seckill;

import com.sinrotic.rs.order.service.OrderServiceException;
import org.springframework.stereotype.Component;

@Component
public class ConfiguredSeckillOrderItemResolver implements SeckillOrderItemResolver {

    private final SeckillActivityProperties properties;

    public ConfiguredSeckillOrderItemResolver(SeckillActivityProperties properties) {
        this.properties = properties;
    }

    @Override
    public SeckillOrderItemSnapshot resolve(String activityId, String itemId, String skuId) {
        String normalizedActivityId = requireText(activityId, "activityId");
        String normalizedItemId = requireText(itemId, "itemId");
        String normalizedSkuId = requireText(skuId, "skuId");

        SeckillActivityProperties.Activity activity =
                properties.getActivities().get(normalizedActivityId);
        if (activity == null) {
            throw missingConfig(normalizedActivityId, normalizedItemId, normalizedSkuId);
        }

        SeckillActivityProperties.Item item = activity.getItems().get(normalizedItemId);
        if (item == null) {
            throw missingConfig(normalizedActivityId, normalizedItemId, normalizedSkuId);
        }

        SeckillActivityProperties.Sku sku = item.getSkus().get(normalizedSkuId);
        if (sku == null) {
            throw missingConfig(normalizedActivityId, normalizedItemId, normalizedSkuId);
        }

        return new SeckillOrderItemSnapshot(normalizedItemId, sku.getItemTitle(), sku.getUnitPrice());
    }

    private OrderServiceException missingConfig(String activityId, String itemId, String skuId) {
        return new OrderServiceException(
                "seckill item config is missing for activityId=" + activityId
                        + ", itemId=" + itemId
                        + ", skuId=" + skuId
        );
    }

    private String requireText(String value, String fieldName) {
        if (value == null || value.isBlank()) {
            throw new OrderServiceException(fieldName + " is required");
        }
        return value.trim();
    }
}
