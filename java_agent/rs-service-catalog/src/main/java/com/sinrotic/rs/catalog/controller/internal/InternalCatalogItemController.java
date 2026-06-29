package com.sinrotic.rs.catalog.controller.internal;

import com.sinrotic.rs.catalog.domain.dto.BatchItemIdsRequestDTO;
import com.sinrotic.rs.catalog.domain.vo.CatalogItemCardVO;
import com.sinrotic.rs.catalog.domain.vo.CatalogItemDetailVO;
import com.sinrotic.rs.catalog.service.CatalogService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/internal/catalog/items")
public class InternalCatalogItemController {

    private final CatalogService catalogService;

    public InternalCatalogItemController(CatalogService catalogService) {
        this.catalogService = catalogService;
    }

    @PostMapping("/cards")
    public List<CatalogItemCardVO> listItemCards(@RequestBody BatchItemIdsRequestDTO request) {
        return catalogService.listItemCards(request);
    }

    @PostMapping("/details")
    public List<CatalogItemDetailVO> listItemDetails(@RequestBody BatchItemIdsRequestDTO request) {
        return catalogService.listItemDetails(request);
    }
}
