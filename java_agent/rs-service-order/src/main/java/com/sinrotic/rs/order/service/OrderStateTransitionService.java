package com.sinrotic.rs.order.service;

import com.sinrotic.rs.order.domain.entity.OrderItem;
import com.sinrotic.rs.order.mapper.OrderItemMapper;
import com.sinrotic.rs.order.mapper.OrderMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class OrderStateTransitionService {

    private final OrderMapper orderMapper;
    private final OrderItemMapper orderItemMapper;

    public OrderStateTransitionService(OrderMapper orderMapper, OrderItemMapper orderItemMapper) {
        this.orderMapper = orderMapper;
        this.orderItemMapper = orderItemMapper;
    }

    @Transactional(rollbackFor = Exception.class)
    public StockMovement markPaidTransition(Long orderId) {
        int updated = orderMapper.markPaid(orderId);
        if (updated == 0) {
            return null;
        }
        return movementFor(orderId);
    }

    @Transactional(rollbackFor = Exception.class)
    public StockMovement closeTimeoutTransition(Long orderId) {
        int updated = orderMapper.closeTimeout(orderId);
        if (updated == 0) {
            return null;
        }
        return movementFor(orderId);
    }

    @Transactional(rollbackFor = Exception.class)
    public StockMovement cancelTransition(Long orderId) {
        int updated = orderMapper.cancel(orderId);
        if (updated == 0) {
            return null;
        }
        return movementFor(orderId);
    }

    private StockMovement movementFor(Long orderId) {
        OrderItem orderItem = orderItemMapper.findByOrderId(orderId);
        if (orderItem == null) {
            throw new OrderServiceException("order item not found");
        }
        return new StockMovement(orderId, orderItem.getSkuId(), orderItem.getQuantity());
    }
}
