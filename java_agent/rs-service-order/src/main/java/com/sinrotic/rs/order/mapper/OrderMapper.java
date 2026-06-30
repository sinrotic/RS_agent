package com.sinrotic.rs.order.mapper;

import com.sinrotic.rs.order.domain.entity.Order;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

@Mapper
public interface OrderMapper {

    int insertOrder(Order order);

    int markPaid(@Param("orderId") Long orderId);

    int closeTimeout(@Param("orderId") Long orderId);

    int cancel(@Param("orderId") Long orderId);

    Order findByRequestId(@Param("requestId") String requestId);

    Order findByOrderId(@Param("orderId") Long orderId);
}
