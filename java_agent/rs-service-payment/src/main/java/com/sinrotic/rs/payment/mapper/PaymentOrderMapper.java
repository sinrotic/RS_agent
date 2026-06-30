package com.sinrotic.rs.payment.mapper;

import com.sinrotic.rs.payment.domain.entity.PaymentOrder;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

@Mapper
public interface PaymentOrderMapper {

    int insertPayment(
            @Param("paymentId") Long paymentId,
            @Param("orderId") Long orderId,
            @Param("provider") String provider,
            @Param("amount") Long amount,
            @Param("status") String status
    );

    int markPaid(
            @Param("orderId") Long orderId,
            @Param("provider") String provider,
            @Param("amount") Long amount,
            @Param("providerTransactionId") String providerTransactionId
    );

    PaymentOrder findByOrderId(@Param("orderId") Long orderId);
}
