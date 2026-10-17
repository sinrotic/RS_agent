package com.sinrotic.rs.catalog.controller;

import com.sinrotic.rs.catalog.controller.app.CatalogItemController;
import com.sinrotic.rs.catalog.service.CatalogService;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class CatalogItemControllerTest {

    @Test
    void detailReturnsNotFoundForUnknownCatalogItem() throws Exception {
        CatalogService catalogService = mock(CatalogService.class);
        when(catalogService.getItemDetail("UNKNOWN")).thenReturn(null);
        MockMvc mockMvc = MockMvcBuilders
                .standaloneSetup(new CatalogItemController(catalogService))
                .build();

        mockMvc.perform(get("/api/catalog/items/UNKNOWN"))
                .andExpect(status().isNotFound());
    }
}
