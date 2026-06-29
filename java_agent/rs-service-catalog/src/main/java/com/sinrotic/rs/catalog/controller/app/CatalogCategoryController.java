package com.sinrotic.rs.catalog.controller.app;

import com.sinrotic.rs.catalog.domain.dto.CatalogItemPageRequestDTO;
import com.sinrotic.rs.catalog.domain.vo.CatalogCategoryVO;
import com.sinrotic.rs.catalog.domain.vo.CatalogItemCardVO;
import com.sinrotic.rs.catalog.service.CatalogService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/catalog/categories")
public class CatalogCategoryController {

    private final CatalogService catalogService;

    public CatalogCategoryController(CatalogService catalogService) {
        this.catalogService = catalogService;
    }

    @GetMapping
    public List<CatalogCategoryVO> listCategories() {
        return catalogService.listCategories();
    }

    @GetMapping("/{categoryId}/items")
    public List<CatalogItemCardVO> listItemsByCategory(
            @PathVariable String categoryId,
            @RequestParam(required = false) Integer limit
    ) {
        return catalogService.listItemsByCategory(new CatalogItemPageRequestDTO(categoryId, limit));
    }
}
