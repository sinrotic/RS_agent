package com.sinrotic.rs.inventory.service;

import com.sinrotic.rs.inventory.domain.dto.InventoryLockRequestDTO;
import com.sinrotic.rs.inventory.domain.dto.InventoryConfirmRequestDTO;
import com.sinrotic.rs.inventory.domain.dto.InventoryReleaseRequestDTO;
import com.sinrotic.rs.inventory.domain.entity.StockLog;
import com.sinrotic.rs.inventory.mapper.SkuStockMapper;
import com.sinrotic.rs.inventory.mapper.StockLogMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.transaction.annotation.Transactional;

import java.lang.reflect.Method;
import java.time.LocalDateTime;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class InventoryServiceTest {

    private SkuStockMapper skuStockMapper;
    private StockLogMapper stockLogMapper;
    private InventoryService inventoryService;

    @BeforeEach
    void setUp() {
        skuStockMapper = mock(SkuStockMapper.class);
        stockLogMapper = mock(StockLogMapper.class);
        inventoryService = new InventoryService(skuStockMapper, stockLogMapper);
    }

    @Test
    void lockStockDeclaresRollbackForException() throws NoSuchMethodException {
        Method lockStock = InventoryService.class.getMethod("lockStock", InventoryLockRequestDTO.class);

        Transactional transactional = lockStock.getAnnotation(Transactional.class);

        assertNotNull(transactional);
        assertEquals(1, transactional.rollbackFor().length);
        assertSame(Exception.class, transactional.rollbackFor()[0]);
    }

    @Test
    void lockStockRejectsInvalidRequest() {
        InventoryLockRequestDTO request = new InventoryLockRequestDTO(" ", 1L, "sku-1", 1);

        assertThrows(InventoryServiceException.class, () -> inventoryService.lockStock(request));

        verify(stockLogMapper, never()).insertLog(any());
        verify(skuStockMapper, never()).lockStock(any(), any());
    }

    @Test
    void lockStockReturnsWithoutUpdatingWhenEquivalentLogExists() {
        InventoryLockRequestDTO request = new InventoryLockRequestDTO("req-1", 10L, "sku-1", 2);
        when(stockLogMapper.findSameLog("req-1", 10L, "sku-1", "LOCK"))
                .thenReturn(log("req-1", 10L, "sku-1", 2, "LOCK"));

        inventoryService.lockStock(request);

        verify(stockLogMapper, never()).insertLog(any());
        verify(skuStockMapper, never()).lockStock(any(), any());
    }

    @Test
    void lockStockInsertsLogAndUpdatesStock() {
        InventoryLockRequestDTO request = new InventoryLockRequestDTO("req-1", 10L, "sku-1", 2);
        when(stockLogMapper.insertLog(any())).thenReturn(1);
        when(skuStockMapper.lockStock("sku-1", 2)).thenReturn(1);

        inventoryService.lockStock(request);

        verify(stockLogMapper).insertLog(any(StockLog.class));
        verify(skuStockMapper).lockStock("sku-1", 2);
    }

    @Test
    void lockStockDuplicateInsertReturnsSuccessForEquivalentLogWithoutUpdatingAgain() {
        InventoryLockRequestDTO request = new InventoryLockRequestDTO("req-1", 10L, "sku-1", 2);
        when(stockLogMapper.insertLog(any()))
                .thenThrow(new DuplicateKeyException("duplicate stock log"));
        when(stockLogMapper.findSameLog("req-1", 10L, "sku-1", "LOCK"))
                .thenReturn(null);
        when(stockLogMapper.findSameLogForUpdate("req-1", 10L, "sku-1", "LOCK"))
                .thenReturn(log("req-1", 10L, "sku-1", 2, "LOCK"));

        assertDoesNotThrow(() -> inventoryService.lockStock(request));

        verify(stockLogMapper, times(1)).findSameLog("req-1", 10L, "sku-1", "LOCK");
        verify(stockLogMapper).findSameLogForUpdate("req-1", 10L, "sku-1", "LOCK");
        verify(skuStockMapper, never()).lockStock(any(), any());
    }

    @Test
    void lockStockDuplicateInsertThrowsForConflictingLog() {
        InventoryLockRequestDTO request = new InventoryLockRequestDTO("req-1", 10L, "sku-1", 2);
        when(stockLogMapper.insertLog(any()))
                .thenThrow(new DuplicateKeyException("duplicate stock log"));
        when(stockLogMapper.findSameLog("req-1", 10L, "sku-1", "LOCK"))
                .thenReturn(null);
        when(stockLogMapper.findSameLogForUpdate("req-1", 10L, "sku-1", "LOCK"))
                .thenReturn(log("req-1", 10L, "sku-1", 3, "LOCK"));

        assertThrows(InventoryServiceException.class, () -> inventoryService.lockStock(request));

        verify(skuStockMapper, never()).lockStock(any(), any());
    }

    @Test
    void lockStockThrowsWhenConditionalStockUpdateFails() {
        InventoryLockRequestDTO request = new InventoryLockRequestDTO("req-1", 10L, "sku-1", 2);
        when(stockLogMapper.insertLog(any())).thenReturn(1);
        when(skuStockMapper.lockStock("sku-1", 2)).thenReturn(0);

        assertThrows(InventoryServiceException.class, () -> inventoryService.lockStock(request));

        verify(stockLogMapper).insertLog(any(StockLog.class));
        verify(skuStockMapper).lockStock("sku-1", 2);
    }

    @Test
    void confirmDeductUsesConfirmTypeAndMapperOperation() {
        InventoryConfirmRequestDTO request = new InventoryConfirmRequestDTO("req-2", 10L, "sku-1", 2);
        when(stockLogMapper.findByOrderSkuType(10L, "sku-1", "LOCK"))
                .thenReturn(log("lock-req", 10L, "sku-1", 2, "LOCK"));
        when(stockLogMapper.insertLog(any())).thenReturn(1);
        when(skuStockMapper.confirmDeduct("sku-1", 2)).thenReturn(1);

        inventoryService.confirmDeduct(request);

        verify(stockLogMapper).findSameLog("req-2", 10L, "sku-1", "CONFIRM");
        verify(skuStockMapper).confirmDeduct("sku-1", 2);
    }

    @Test
    void confirmDeductThrowsWhenNoMatchingLockLogExists() {
        InventoryConfirmRequestDTO request = new InventoryConfirmRequestDTO("req-2", 10L, "sku-1", 2);

        assertThrows(InventoryServiceException.class, () -> inventoryService.confirmDeduct(request));

        verify(stockLogMapper).findByOrderSkuType(10L, "sku-1", "LOCK");
        verify(stockLogMapper, never()).insertLog(any());
        verify(skuStockMapper, never()).confirmDeduct(any(), any());
    }

    @Test
    void confirmDeductThrowsWhenLockQuantityDoesNotMatch() {
        InventoryConfirmRequestDTO request = new InventoryConfirmRequestDTO("req-2", 10L, "sku-1", 2);
        when(stockLogMapper.findByOrderSkuType(10L, "sku-1", "LOCK"))
                .thenReturn(log("lock-req", 10L, "sku-1", 1, "LOCK"));

        assertThrows(InventoryServiceException.class, () -> inventoryService.confirmDeduct(request));

        verify(stockLogMapper, never()).insertLog(any());
        verify(skuStockMapper, never()).confirmDeduct(any(), any());
    }

    @Test
    void releaseStockUsesReleaseTypeAndMapperOperation() {
        InventoryReleaseRequestDTO request = new InventoryReleaseRequestDTO("req-3", 10L, "sku-1", 2);
        when(stockLogMapper.findByOrderSkuType(10L, "sku-1", "LOCK"))
                .thenReturn(log("lock-req", 10L, "sku-1", 2, "LOCK"));
        when(stockLogMapper.insertLog(any())).thenReturn(1);
        when(skuStockMapper.releaseStock("sku-1", 2)).thenReturn(1);

        inventoryService.releaseStock(request);

        verify(stockLogMapper).findSameLog("req-3", 10L, "sku-1", "RELEASE");
        verify(skuStockMapper).releaseStock("sku-1", 2);
    }

    @Test
    void releaseStockThrowsWhenNoMatchingLockLogExists() {
        InventoryReleaseRequestDTO request = new InventoryReleaseRequestDTO("req-3", 10L, "sku-1", 2);

        assertThrows(InventoryServiceException.class, () -> inventoryService.releaseStock(request));

        verify(stockLogMapper).findByOrderSkuType(10L, "sku-1", "LOCK");
        verify(stockLogMapper, never()).insertLog(any());
        verify(skuStockMapper, never()).releaseStock(any(), any());
    }

    private StockLog log(String requestId, Long orderId, String skuId, Integer quantity, String type) {
        return new StockLog(1L, requestId, orderId, skuId, quantity, type, LocalDateTime.now());
    }
}
