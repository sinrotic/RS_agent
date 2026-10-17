package com.sinrotic.rs.inventory.controller.app;

import com.sinrotic.rs.inventory.domain.vo.ItemAvailabilityVO;
import com.sinrotic.rs.inventory.service.InventoryService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class AppInventoryControllerTest {

    private InventoryService inventoryService;
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        inventoryService = mock(InventoryService.class);
        mockMvc = MockMvcBuilders.standaloneSetup(new AppInventoryController(inventoryService)).build();
    }

    @Test
    void returnsAggregatedAvailability() throws Exception {
        when(inventoryService.getItemAvailability("item-1"))
                .thenReturn(new ItemAvailabilityVO("item-1", 2, 7));

        mockMvc.perform(get("/api/inventory/items/item-1/availability"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.item_id").value("item-1"))
                .andExpect(jsonPath("$.sku_count").value(2))
                .andExpect(jsonPath("$.available_stock").value(7))
                .andExpect(jsonPath("$.available").value(true));
    }

    @Test
    void returnsNotFoundWhenNoInventoryProjectionExists() throws Exception {
        when(inventoryService.getItemAvailability("missing")).thenReturn(null);

        mockMvc.perform(get("/api/inventory/items/missing/availability"))
                .andExpect(status().isNotFound());
    }
}
