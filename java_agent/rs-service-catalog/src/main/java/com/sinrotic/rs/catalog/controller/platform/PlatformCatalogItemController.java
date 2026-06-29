package com.sinrotic.rs.catalog.controller.platform;

import com.sinrotic.rs.catalog.domain.dto.BatchItemIdsRequestDTO;
import com.sinrotic.rs.catalog.domain.vo.CatalogItemDetailVO;
import com.sinrotic.rs.catalog.domain.vo.CatalogItemTextVO;
import com.sinrotic.rs.catalog.service.CatalogService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/platform/catalog/items")
public class PlatformCatalogItemController {

    private final CatalogService catalogService;

    public PlatformCatalogItemController(CatalogService catalogService) {
        this.catalogService = catalogService;
    }

    @GetMapping("/{itemId}")
    public CatalogItemDetailVO getItemDetail(@PathVariable String itemId) {
        return catalogService.getItemDetail(itemId);
    }

    @PostMapping("/context")
    public List<CatalogItemTextVO> listItemContext(@RequestBody BatchItemIdsRequestDTO request) {
        return catalogService.listItemTexts(request);
    }
}
