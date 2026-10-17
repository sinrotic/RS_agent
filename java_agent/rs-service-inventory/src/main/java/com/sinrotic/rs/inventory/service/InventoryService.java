package com.sinrotic.rs.inventory.service;

import com.sinrotic.rs.inventory.domain.dto.InventoryConfirmRequestDTO;
import com.sinrotic.rs.inventory.domain.dto.InventoryLockRequestDTO;
import com.sinrotic.rs.inventory.domain.dto.InventoryReleaseRequestDTO;
import com.sinrotic.rs.inventory.domain.entity.StockLog;
import com.sinrotic.rs.inventory.domain.vo.ItemAvailabilityVO;
import com.sinrotic.rs.inventory.mapper.SkuStockMapper;
import com.sinrotic.rs.inventory.mapper.StockLogMapper;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class InventoryService {

    private static final String TYPE_LOCK = "LOCK";
    private static final String TYPE_CONFIRM = "CONFIRM";
    private static final String TYPE_RELEASE = "RELEASE";
    private static final String TYPE_CANCEL = "CANCEL";

    private final SkuStockMapper skuStockMapper;
    private final StockLogMapper stockLogMapper;

    public InventoryService(SkuStockMapper skuStockMapper, StockLogMapper stockLogMapper) {
        this.skuStockMapper = skuStockMapper;
        this.stockLogMapper = stockLogMapper;
    }

    public ItemAvailabilityVO getItemAvailability(String itemId) {
        if (isBlank(itemId)) {
            throw new InventoryServiceException("itemId is required");
        }
        return skuStockMapper.findItemAvailability(itemId.trim());
    }

    @Transactional(rollbackFor = Exception.class)
    public void lockStock(InventoryLockRequestDTO request) {
        if (request == null) {
            throw new InventoryServiceException("request is required");
        }
        process(
                validate(request.requestId(), request.orderId(), request.skuId(), request.quantity()),
                TYPE_LOCK,
                normalizedRequest -> skuStockMapper.lockStock(normalizedRequest.skuId(), normalizedRequest.quantity()),
                "insufficient available stock",
                false
        );
    }

    @Transactional(rollbackFor = Exception.class)
    public void confirmDeduct(InventoryConfirmRequestDTO request) {
        if (request == null) {
            throw new InventoryServiceException("request is required");
        }
        process(
                validate(request.requestId(), request.orderId(), request.skuId(), request.quantity()),
                TYPE_CONFIRM,
                normalizedRequest -> skuStockMapper.confirmDeduct(normalizedRequest.skuId(), normalizedRequest.quantity()),
                "insufficient locked stock to confirm",
                true
        );
    }

    @Transactional(rollbackFor = Exception.class)
    public void releaseStock(InventoryReleaseRequestDTO request) {
        if (request == null) {
            throw new InventoryServiceException("request is required");
        }
        process(
                validate(request.requestId(), request.orderId(), request.skuId(), request.quantity()),
                TYPE_RELEASE,
                normalizedRequest -> skuStockMapper.releaseStock(normalizedRequest.skuId(), normalizedRequest.quantity()),
                "insufficient locked stock to release",
                true
        );
    }

    /** 取消创建阶段的未知预留：没有 LOCK 也登记取消，阻止迟到的 LOCK。 */
    @Transactional(rollbackFor = Exception.class)
    public void cancelReservation(InventoryReleaseRequestDTO input) {
        if (input == null) throw new InventoryServiceException("request is required");
        StockMovementRequest request = validate(input.requestId(),input.orderId(),input.skuId(),input.quantity());
        skuStockMapper.lockSkuForUpdate(request.skuId());
        StockLog canceled = stockLogMapper.findByOrderSkuTypeForUpdate(request.orderId(),request.skuId(),TYPE_CANCEL);
        if (canceled != null) {
            validateEquivalentLog(canceled,request,TYPE_CANCEL);
            return;
        }
        if (stockLogMapper.findByOrderSkuTypeForUpdate(request.orderId(),request.skuId(),TYPE_CONFIRM) != null)
            throw new InventoryServiceException("confirmed stock reservation cannot be canceled");
        StockLog locked = stockLogMapper.findByOrderSkuTypeForUpdate(request.orderId(),request.skuId(),TYPE_LOCK);
        if (locked != null && !request.quantity().equals(locked.quantity()))
            throw new InventoryServiceException("conflicting stock quantity");
        stockLogMapper.insertLog(toLog(request,TYPE_CANCEL));
        if (locked != null && stockLogMapper.findByOrderSkuTypeForUpdate(request.orderId(),request.skuId(),TYPE_RELEASE) == null
                && skuStockMapper.releaseStock(request.skuId(),request.quantity()) != 1)
            throw new InventoryServiceException("failed to release canceled stock reservation");
    }

    private StockMovementRequest validate(String requestId, Long orderId, String skuId, Integer quantity) {
        if (isBlank(requestId)) {
            throw new InventoryServiceException("requestId is required");
        }
        if (orderId == null) {
            throw new InventoryServiceException("orderId is required");
        }
        if (isBlank(skuId)) {
            throw new InventoryServiceException("skuId is required");
        }
        if (quantity == null || quantity <= 0) {
            throw new InventoryServiceException("quantity must be positive");
        }
        return new StockMovementRequest(requestId.trim(), orderId, skuId.trim(), quantity);
    }

    private void process(
            StockMovementRequest request,
            String type,
            StockUpdater stockUpdater,
            String updateFailureMessage,
            boolean requiresMatchingLock
    ) {
        // LOCK 与取消未知预留共用 SKU 行锁；取消先到时，迟到的锁定不能重新占用库存。
        skuStockMapper.lockSkuForUpdate(request.skuId());
        if (stockLogMapper.findByOrderSkuTypeForUpdate(request.orderId(),request.skuId(),TYPE_CANCEL) != null)
            throw new InventoryServiceException("stock reservation has been canceled");
        StockLog existingLog = stockLogMapper.findSameLog(request.requestId(), request.orderId(), request.skuId(), type);
        if (existingLog != null) {
            validateEquivalentLog(existingLog, request, type);
            return;
        }

        if (requiresMatchingLock) {
            validateMatchingLock(request);
            String opposite = TYPE_CONFIRM.equals(type) ? TYPE_RELEASE : TYPE_CONFIRM;
            if (stockLogMapper.findByOrderSkuTypeForUpdate(request.orderId(), request.skuId(), opposite) != null) {
                throw new InventoryServiceException("stock reservation already reached the opposite terminal state");
            }
        }

        try {
            stockLogMapper.insertLog(toLog(request, type));
        } catch (DuplicateKeyException ex) {
            StockLog duplicateLog = stockLogMapper.findSameLogForUpdate(request.requestId(), request.orderId(), request.skuId(), type);
            if (duplicateLog != null && isEquivalentLog(duplicateLog, request, type)) {
                return;
            }
            throw new InventoryServiceException("conflicting stock log", ex);
        }

        int updatedRows = stockUpdater.update(request);
        if (updatedRows != 1) {
            throw new InventoryServiceException(updateFailureMessage);
        }
    }

    private StockLog toLog(StockMovementRequest request, String type) {
        return new StockLog(null, request.requestId(), request.orderId(), request.skuId(), request.quantity(), type, null);
    }

    private void validateMatchingLock(StockMovementRequest request) {
        // 同一预留的终态操作锁住相同 LOCK 行；使用当前读，避免快照漏看刚提交的终态。
        StockLog lockLog = stockLogMapper.findByOrderSkuTypeForUpdate(request.orderId(), request.skuId(), TYPE_LOCK);
        if (lockLog == null || !request.quantity().equals(lockLog.quantity())) {
            throw new InventoryServiceException("matching lock stock log is required");
        }
    }

    private void validateEquivalentLog(StockLog stockLog, StockMovementRequest request, String type) {
        if (!isEquivalentLog(stockLog, request, type)) {
            throw new InventoryServiceException("conflicting stock log");
        }
    }

    private boolean isEquivalentLog(StockLog stockLog, StockMovementRequest request, String type) {
        return request.requestId().equals(stockLog.requestId())
                && request.orderId().equals(stockLog.orderId())
                && request.skuId().equals(stockLog.skuId())
                && request.quantity().equals(stockLog.quantity())
                && type.equals(stockLog.type());
    }

    private boolean isBlank(String value) {
        return value == null || value.isBlank();
    }

    @FunctionalInterface
    private interface StockUpdater {
        int update(StockMovementRequest request);
    }

    private record StockMovementRequest(String requestId, Long orderId, String skuId, Integer quantity) {
    }
}
