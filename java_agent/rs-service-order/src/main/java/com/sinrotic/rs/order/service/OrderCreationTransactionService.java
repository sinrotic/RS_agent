package com.sinrotic.rs.order.service;

import com.sinrotic.rs.order.domain.entity.Order;
import com.sinrotic.rs.order.domain.entity.OrderItem;
import com.sinrotic.rs.order.domain.vo.OrderCreateVO;
import com.sinrotic.rs.order.mapper.OrderItemMapper;
import com.sinrotic.rs.order.mapper.OrderMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class OrderCreationTransactionService {

    private final OrderMapper orderMapper;
    private final OrderItemMapper orderItemMapper;

    public OrderCreationTransactionService(OrderMapper orderMapper, OrderItemMapper orderItemMapper) {
        this.orderMapper = orderMapper;
        this.orderItemMapper = orderItemMapper;
    }

    @Transactional(rollbackFor = Exception.class)
    public OrderCreateVO createOrderRows(Order order, OrderItem orderItem) {
        if (orderMapper.insertOrder(order) != 1) {
            throw new OrderServiceException("order insert failed");
        }
        if (orderItemMapper.insertItem(orderItem) != 1) {
            throw new OrderServiceException("order item insert failed");
        }
        return new OrderCreateVO(order.getOrderId(), order.getStatus());
    }
}
