package com.sinrotic.rs.inventory.mapper;

import com.sinrotic.rs.inventory.domain.entity.StockLog;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

@Mapper
public interface StockLogMapper {

    int insertLog(StockLog stockLog);

    StockLog findSameLog(
            @Param("requestId") String requestId,
            @Param("orderId") Long orderId,
            @Param("skuId") String skuId,
            @Param("type") String type
    );

    StockLog findSameLogForUpdate(
            @Param("requestId") String requestId,
            @Param("orderId") Long orderId,
            @Param("skuId") String skuId,
            @Param("type") String type
    );

    StockLog findByOrderSkuType(
            @Param("orderId") Long orderId,
            @Param("skuId") String skuId,
            @Param("type") String type
    );
}
