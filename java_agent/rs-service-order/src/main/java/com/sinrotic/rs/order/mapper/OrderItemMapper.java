package com.sinrotic.rs.order.mapper;

import com.sinrotic.rs.order.domain.entity.OrderItem;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

@Mapper
public interface OrderItemMapper {

    int insertItem(OrderItem orderItem);

    OrderItem findByOrderId(@Param("orderId") Long orderId);
}
