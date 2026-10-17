package com.sinrotic.rs.payment.mapper;

import com.sinrotic.rs.payment.domain.entity.PaymentNotification;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import java.util.List;

@Mapper
public interface PaymentNotificationMapper {
    int enqueue(@Param("orderId") Long orderId, @Param("provider") String provider, @Param("transactionId") String transactionId);
    List<Long> dueOrderIds();
    int claim(@Param("orderId") Long orderId, @Param("token") String token);
    PaymentNotification findByOrderId(@Param("orderId") Long orderId);
    int complete(@Param("orderId") Long orderId, @Param("token") String token);
    int retry(@Param("orderId") Long orderId, @Param("token") String token, @Param("status") String status,
              @Param("delaySeconds") long delaySeconds, @Param("error") String error);
}
