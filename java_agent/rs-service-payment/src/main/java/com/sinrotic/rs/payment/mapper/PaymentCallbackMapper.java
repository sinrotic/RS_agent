package com.sinrotic.rs.payment.mapper;

import com.sinrotic.rs.payment.domain.entity.PaymentCallback;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

@Mapper
public interface PaymentCallbackMapper {

    int insertCallback(
            @Param("provider") String provider,
            @Param("providerTransactionId") String providerTransactionId,
            @Param("orderId") Long orderId,
            @Param("amount") Long amount,
            @Param("status") String status,
            @Param("payloadHash") String payloadHash
    );

    PaymentCallback findByProviderTransaction(
            @Param("provider") String provider,
            @Param("providerTransactionId") String providerTransactionId
    );
}
