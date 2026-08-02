package com.sinrotic.rs.catalog.controller.app;

import com.sinrotic.rs.catalog.domain.dto.BatchItemIdsRequestDTO;
import com.sinrotic.rs.catalog.domain.vo.CatalogItemCardVO;
import com.sinrotic.rs.catalog.service.CatalogService;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.math.BigDecimal;
import java.util.List;

import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class CatalogItemControllerTest {

    @Test
    void batchCardsAcceptsSnakeCaseItemIdsAndReturnsCatalogCardFields() throws Exception {
        CatalogService catalogService = mock(CatalogService.class);
        MockMvc mockMvc = MockMvcBuilders.standaloneSetup(new CatalogItemController(catalogService)).build();

        when(catalogService.listItemCards(argThat(request -> request.normalizedItemIds()
                .equals(List.of("B002", "B001", "B002")))))
                .thenReturn(List.of(new CatalogItemCardVO(
                        "B002",
                        "Desk Organizer",
                        "Workspace",
                        "Home Box",
                        "Home Box Store",
                        new BigDecimal("18.50"),
                        "https://example.com/organizer.jpg",
                        "Compact organizer for office supplies"
                )));

        mockMvc.perform(post("/api/catalog/items/batch")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"item_ids":[" B002 ","", "B001", "B002"]}
                                """))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$[0].item_id").value("B002"))
                .andExpect(jsonPath("$[0].store_name").value("Home Box Store"))
                .andExpect(jsonPath("$[0].image_url").value("https://example.com/organizer.jpg"))
                .andExpect(jsonPath("$[0].price").value(18.50));

        verify(catalogService).listItemCards(argThat(request -> request.normalizedItemIds()
                .equals(List.of("B002", "B001", "B002"))));
    }
}
