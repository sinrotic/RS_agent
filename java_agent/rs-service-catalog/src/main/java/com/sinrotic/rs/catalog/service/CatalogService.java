package com.sinrotic.rs.catalog.service;

import com.sinrotic.rs.catalog.domain.dto.BatchItemIdsRequestDTO;
import com.sinrotic.rs.catalog.domain.dto.CatalogItemEmbeddingPageRequestDTO;
import com.sinrotic.rs.catalog.domain.dto.CatalogItemPageRequestDTO;
import com.sinrotic.rs.catalog.domain.vo.CatalogCategoryVO;
import com.sinrotic.rs.catalog.domain.vo.CatalogItemCardVO;
import com.sinrotic.rs.catalog.domain.vo.CatalogItemDetailVO;
import com.sinrotic.rs.catalog.domain.vo.CatalogItemEmbeddingTextVO;
import com.sinrotic.rs.catalog.domain.vo.CatalogItemTextVO;
import com.sinrotic.rs.catalog.domain.vo.VirtualStoreVO;

import java.util.List;

public interface CatalogService {

    CatalogItemDetailVO getItemDetail(String itemId);

    List<CatalogItemCardVO> listItemCards(BatchItemIdsRequestDTO request);

    List<CatalogItemDetailVO> listItemDetails(BatchItemIdsRequestDTO request);

    List<CatalogItemTextVO> listItemTexts(BatchItemIdsRequestDTO request);

    List<CatalogItemEmbeddingTextVO> listItemEmbeddingTexts(BatchItemIdsRequestDTO request);

    List<CatalogItemEmbeddingTextVO> listActiveItemEmbeddingTexts(CatalogItemEmbeddingPageRequestDTO request);

    List<CatalogItemCardVO> listItemsByCategory(CatalogItemPageRequestDTO request);

    List<CatalogItemCardVO> listItemsByStore(CatalogItemPageRequestDTO request);

    List<CatalogCategoryVO> listCategories();

    List<VirtualStoreVO> listStores();
}
