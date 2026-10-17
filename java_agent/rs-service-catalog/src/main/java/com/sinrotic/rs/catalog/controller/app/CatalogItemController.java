package com.sinrotic.rs.catalog.controller.app;

import com.sinrotic.rs.catalog.domain.dto.BatchItemIdsRequestDTO;
import com.sinrotic.rs.catalog.domain.vo.CatalogItemCardVO;
import com.sinrotic.rs.catalog.domain.vo.CatalogItemDetailVO;
import com.sinrotic.rs.catalog.service.CatalogService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;

import java.util.List;

@RestController
@RequestMapping("/api/catalog/items")
public class CatalogItemController {

    private final CatalogService catalogService;

    public CatalogItemController(CatalogService catalogService) {
        this.catalogService = catalogService;
    }

    @GetMapping("/{itemId}")
    public CatalogItemDetailVO getItemDetail(@PathVariable String itemId) {
        CatalogItemDetailVO detail = catalogService.getItemDetail(itemId);
        if (detail == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "catalog item not found");
        }
        return detail;
    }

    @PostMapping("/batch")
    public List<CatalogItemCardVO> listItemCards(@RequestBody BatchItemIdsRequestDTO request) {
        return catalogService.listItemCards(request);
    }
}
