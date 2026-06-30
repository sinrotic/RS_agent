package com.sinrotic.rs.catalog.controller.internal;

import com.sinrotic.rs.catalog.domain.dto.BatchItemIdsRequestDTO;
import com.sinrotic.rs.catalog.domain.dto.CatalogItemEmbeddingPageRequestDTO;
import com.sinrotic.rs.catalog.domain.vo.CatalogItemEmbeddingTextVO;
import com.sinrotic.rs.catalog.domain.vo.CatalogItemTextVO;
import com.sinrotic.rs.catalog.service.CatalogService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/internal/catalog/context")
public class InternalCatalogContextController {

    private final CatalogService catalogService;

    public InternalCatalogContextController(CatalogService catalogService) {
        this.catalogService = catalogService;
    }

    @PostMapping("/item-texts")
    public List<CatalogItemTextVO> listItemTexts(@RequestBody BatchItemIdsRequestDTO request) {
        return catalogService.listItemTexts(request);
    }

    @PostMapping("/rag-documents")
    public List<CatalogItemTextVO> listRagDocuments(@RequestBody BatchItemIdsRequestDTO request) {
        return catalogService.listItemTexts(request);
    }

    @PostMapping("/item-embedding-texts")
    public List<CatalogItemEmbeddingTextVO> listItemEmbeddingTexts(@RequestBody BatchItemIdsRequestDTO request) {
        return catalogService.listItemEmbeddingTexts(request);
    }

    @PostMapping("/active-item-embedding-texts")
    public List<CatalogItemEmbeddingTextVO> listActiveItemEmbeddingTexts(
            @RequestBody CatalogItemEmbeddingPageRequestDTO request
    ) {
        return catalogService.listActiveItemEmbeddingTexts(request);
    }
}
