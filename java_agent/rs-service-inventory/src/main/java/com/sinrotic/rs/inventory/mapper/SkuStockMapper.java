package com.sinrotic.rs.inventory.mapper;

import com.sinrotic.rs.inventory.domain.vo.ItemAvailabilityVO;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

@Mapper
public interface SkuStockMapper {

    void lockSkuForUpdate(@Param("skuId") String skuId);

    ItemAvailabilityVO findItemAvailability(@Param("itemId") String itemId);

    int lockStock(@Param("skuId") String skuId, @Param("quantity") Integer quantity);

    int confirmDeduct(@Param("skuId") String skuId, @Param("quantity") Integer quantity);

    int releaseStock(@Param("skuId") String skuId, @Param("quantity") Integer quantity);
}
