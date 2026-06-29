package com.sinrotic.rs.catalog.controller.app;

import com.sinrotic.rs.catalog.domain.dto.CatalogItemPageRequestDTO;
import com.sinrotic.rs.catalog.domain.vo.CatalogItemCardVO;
import com.sinrotic.rs.catalog.domain.vo.VirtualStoreVO;
import com.sinrotic.rs.catalog.service.CatalogService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/catalog/stores")
public class VirtualStoreController {

    private final CatalogService catalogService;

    public VirtualStoreController(CatalogService catalogService) {
        this.catalogService = catalogService;
    }

    @GetMapping
    public List<VirtualStoreVO> listStores() {
        return catalogService.listStores();
    }

    @GetMapping("/{storeId}/items")
    public List<CatalogItemCardVO> listItemsByStore(
            @PathVariable String storeId,
            @RequestParam(required = false) Integer limit
    ) {
        return catalogService.listItemsByStore(new CatalogItemPageRequestDTO(storeId, limit));
    }
}
