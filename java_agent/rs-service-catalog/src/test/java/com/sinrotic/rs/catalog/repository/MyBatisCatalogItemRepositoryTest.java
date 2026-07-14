package com.sinrotic.rs.catalog.repository;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.catalog.domain.entity.CatalogItem;
import com.sinrotic.rs.catalog.mapper.CatalogItemMapper;
import com.sinrotic.rs.catalog.mapper.CatalogItemRow;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class MyBatisCatalogItemRepositoryTest {

    @Test
    void nestedAttributeValuesArePreservedAsCompactStrings() {
        CatalogItemMapper mapper = mock(CatalogItemMapper.class);
        when(mapper.selectByItemId("A1")).thenReturn(new CatalogItemRow(
                "A1",
                "A1",
                "Title",
                "Office",
                "Office > Supplies",
                "Brand",
                "Store",
                BigDecimal.TEN,
                null,
                "Summary",
                "Description",
                "{\"Color\":\"Black\",\"Best Sellers Rank\":{\"Office Products\":42}}",
                "{}",
                "active"
        ));

        CatalogItem item = new MyBatisCatalogItemRepository(mapper, new ObjectMapper())
                .findByItemId("A1")
                .orElseThrow();

        assertEquals("Black", item.attributes().get("Color"));
        assertEquals("{\"Office Products\":42}", item.attributes().get("Best Sellers Rank"));
    }
}
