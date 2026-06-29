package com.sinrotic.rs.catalog.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.util.List;

@Mapper
public interface CatalogItemMapper {

    CatalogItemRow selectByItemId(@Param("itemId") String itemId);

    List<CatalogItemRow> selectByItemIds(@Param("itemIds") List<String> itemIds);

    List<CatalogItemRow> selectByCategory(@Param("category") String category, @Param("limit") int limit);

    List<CatalogItemRow> selectByStoreName(@Param("storeName") String storeName, @Param("limit") int limit);

    List<String> selectCategories();

    List<String> selectStoreNames();
}
