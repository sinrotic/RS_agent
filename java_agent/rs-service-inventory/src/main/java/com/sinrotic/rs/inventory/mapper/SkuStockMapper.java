package com.sinrotic.rs.inventory.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

@Mapper
public interface SkuStockMapper {

    int lockStock(@Param("skuId") String skuId, @Param("quantity") Integer quantity);

    int confirmDeduct(@Param("skuId") String skuId, @Param("quantity") Integer quantity);

    int releaseStock(@Param("skuId") String skuId, @Param("quantity") Integer quantity);
}
