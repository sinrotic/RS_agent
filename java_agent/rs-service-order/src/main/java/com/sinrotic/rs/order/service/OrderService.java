package com.sinrotic.rs.order.service;

import com.sinrotic.rs.order.client.InventoryClient;
import com.sinrotic.rs.order.domain.dto.CreateOrderRequestDTO;
import com.sinrotic.rs.order.domain.dto.OrderPaidRequestDTO;
import com.sinrotic.rs.order.domain.dto.SeckillOrderCreateMessageDTO;
import com.sinrotic.rs.order.domain.entity.Order;
import com.sinrotic.rs.order.domain.entity.OrderItem;
import com.sinrotic.rs.order.domain.vo.OrderCreateVO;
import com.sinrotic.rs.order.mapper.OrderMapper;
import com.sinrotic.rs.order.service.seckill.SeckillOrderItemResolver;
import com.sinrotic.rs.order.service.seckill.SeckillOrderItemSnapshot;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;

@Service
public class OrderService {

    public static final String STATUS_WAITING_PAYMENT = "WAITING_PAYMENT";
    public static final String STATUS_PAID = "PAID";
    public static final String STATUS_TIMEOUT_CLOSED = "TIMEOUT_CLOSED";
    public static final String STATUS_CANCELED = "CANCELED";
    private static final int LOCK_FAILURE_DUPLICATE_REREAD_ATTEMPTS = 3;
    private static final long LOCK_FAILURE_DUPLICATE_REREAD_DELAY_MILLIS = 25L;

    private final OrderMapper orderMapper;
    private final OrderCreationTransactionService orderCreationTransactionService;
    private final OrderStateTransitionService orderStateTransitionService;
    private final InventoryClient inventoryClient;
    private final IdGenerator idGenerator;
    private final SeckillOrderItemResolver seckillOrderItemResolver;

    public OrderService(
            OrderMapper orderMapper,
            OrderCreationTransactionService orderCreationTransactionService,
            OrderStateTransitionService orderStateTransitionService,
            InventoryClient inventoryClient,
            IdGenerator idGenerator,
            SeckillOrderItemResolver seckillOrderItemResolver
    ) {
        this.orderMapper = orderMapper;
        this.orderCreationTransactionService = orderCreationTransactionService;
        this.orderStateTransitionService = orderStateTransitionService;
        this.inventoryClient = inventoryClient;
        this.idGenerator = idGenerator;
        this.seckillOrderItemResolver = seckillOrderItemResolver;
    }

    public OrderCreateVO createOrder(CreateOrderRequestDTO request) {
        CreateOrderRequestDTO normalized = validateCreateRequest(request);
        Order existingOrder = orderMapper.findByRequestId(normalized.requestId());
        if (existingOrder != null) {
            return new OrderCreateVO(existingOrder.getOrderId(), existingOrder.getStatus());
        }

        long orderId = idGenerator.nextId();
        long totalAmount = calculateTotalAmount(normalized.quantity(), normalized.unitPrice());
        try {
            inventoryClient.lock(normalized.requestId(), orderId, normalized.skuId(), normalized.quantity());
        } catch (RuntimeException lockFailure) {
            Order orderCreatedByDuplicateRequest =
                    findExistingOrderAfterInventoryLockFailure(normalized.requestId(), lockFailure);
            if (orderCreatedByDuplicateRequest != null) {
                return new OrderCreateVO(
                        orderCreatedByDuplicateRequest.getOrderId(),
                        orderCreatedByDuplicateRequest.getStatus()
                );
            }
            throw lockFailure;
        }

        Order order = toOrder(normalized, orderId, totalAmount);
        OrderItem orderItem = toOrderItem(normalized, orderId, totalAmount);
        try {
            return orderCreationTransactionService.createOrderRows(order, orderItem);
        } catch (DuplicateKeyException ex) {
            return returnExistingAfterDuplicateOrder(normalized, orderId, ex);
        } catch (RuntimeException ex) {
            releaseAfterCreateFailure(normalized, orderId, ex);
            throw ex;
        }
    }

    public OrderCreateVO createSeckillOrder(SeckillOrderCreateMessageDTO message) {
        SeckillOrderCreateMessageDTO normalized = validateSeckillOrderCreateMessage(message);
        Order existingOrder = orderMapper.findByRequestId(normalized.requestId());
        if (existingOrder != null) {
            return new OrderCreateVO(existingOrder.getOrderId(), existingOrder.getStatus());
        }

        SeckillOrderItemSnapshot itemSnapshot = seckillOrderItemResolver.resolve(
                normalized.activityId(),
                normalized.itemId(),
                normalized.skuId()
        );
        return createOrder(new CreateOrderRequestDTO(
                normalized.requestId(),
                normalized.accountId(),
                null,
                null,
                null,
                itemSnapshot.itemId(),
                normalized.skuId(),
                itemSnapshot.itemTitle(),
                normalized.quantity(),
                itemSnapshot.unitPrice()
        ));
    }

    public void markPaid(OrderPaidRequestDTO request) {
        OrderPaidRequestDTO normalized = validatePaidRequest(request);
        StockMovement movement = orderStateTransitionService.markPaidTransition(normalized.orderId());
        if (movement == null) {
            return;
        }

        inventoryClient.confirm(normalized.requestId(), normalized.orderId(), movement.skuId(), movement.quantity());
    }

    public void closeTimeout(Long orderId, String requestId) {
        validateOrderId(orderId);
        String normalizedRequestId = defaultRequestId(requestId, "close-timeout", orderId);
        StockMovement movement = orderStateTransitionService.closeTimeoutTransition(orderId);
        if (movement == null) {
            return;
        }

        inventoryClient.release(normalizedRequestId, orderId, movement.skuId(), movement.quantity());
    }

    public void cancel(Long orderId, String requestId) {
        validateOrderId(orderId);
        String normalizedRequestId = defaultRequestId(requestId, "cancel", orderId);
        StockMovement movement = orderStateTransitionService.cancelTransition(orderId);
        if (movement == null) {
            return;
        }

        inventoryClient.release(normalizedRequestId, orderId, movement.skuId(), movement.quantity());
    }

    private CreateOrderRequestDTO validateCreateRequest(CreateOrderRequestDTO request) {
        if (request == null) {
            throw new OrderServiceException("request is required");
        }
        String requestId = requireText(request.requestId(), "requestId");
        if (request.accountId() == null) {
            throw new OrderServiceException("accountId is required");
        }
        String itemId = requireText(request.itemId(), "itemId");
        String skuId = requireText(request.skuId(), "skuId");
        String itemTitle = requireText(request.itemTitle(), "itemTitle");
        if (request.quantity() == null || request.quantity() <= 0) {
            throw new OrderServiceException("quantity must be positive");
        }
        if (request.unitPrice() == null || request.unitPrice() <= 0) {
            throw new OrderServiceException("unitPrice must be positive");
        }
        return new CreateOrderRequestDTO(
                requestId,
                request.accountId(),
                trimToNull(request.profileUserId()),
                trimToNull(request.sessionId()),
                trimToNull(request.recommendRequestId()),
                itemId,
                skuId,
                itemTitle,
                request.quantity(),
                request.unitPrice()
        );
    }

    private SeckillOrderCreateMessageDTO validateSeckillOrderCreateMessage(SeckillOrderCreateMessageDTO message) {
        if (message == null) {
            throw new OrderServiceException("message is required");
        }
        String requestId = requireText(message.requestId(), "requestId");
        if (message.accountId() == null) {
            throw new OrderServiceException("accountId is required");
        }
        requireText(message.activityId(), "activityId");
        String itemId = requireText(message.itemId(), "itemId");
        String skuId = requireText(message.skuId(), "skuId");
        if (message.quantity() == null || message.quantity() <= 0) {
            throw new OrderServiceException("quantity must be positive");
        }
        return new SeckillOrderCreateMessageDTO(
                requestId,
                message.accountId(),
                message.activityId().trim(),
                itemId,
                skuId,
                message.quantity()
        );
    }

    private OrderPaidRequestDTO validatePaidRequest(OrderPaidRequestDTO request) {
        if (request == null) {
            throw new OrderServiceException("request is required");
        }
        String requestId = requireText(request.requestId(), "requestId");
        validateOrderId(request.orderId());
        return new OrderPaidRequestDTO(
                requestId,
                request.orderId(),
                trimToNull(request.provider()),
                trimToNull(request.providerTransactionId())
        );
    }

    private void validateOrderId(Long orderId) {
        if (orderId == null) {
            throw new OrderServiceException("orderId is required");
        }
    }

    private long calculateTotalAmount(Integer quantity, Long unitPrice) {
        try {
            return Math.multiplyExact(unitPrice, quantity.longValue());
        } catch (ArithmeticException ex) {
            throw new OrderServiceException("totalAmount overflow", ex);
        }
    }

    private Order toOrder(CreateOrderRequestDTO request, long orderId, long totalAmount) {
        Order order = new Order();
        order.setOrderId(orderId);
        order.setRequestId(request.requestId());
        order.setAccountId(request.accountId());
        order.setProfileUserId(request.profileUserId());
        order.setSessionId(request.sessionId());
        order.setRecommendRequestId(request.recommendRequestId());
        order.setStatus(STATUS_WAITING_PAYMENT);
        order.setTotalAmount(totalAmount);
        return order;
    }

    private OrderItem toOrderItem(CreateOrderRequestDTO request, long orderId, long totalAmount) {
        OrderItem orderItem = new OrderItem();
        orderItem.setOrderId(orderId);
        orderItem.setItemId(request.itemId());
        orderItem.setSkuId(request.skuId());
        orderItem.setItemTitle(request.itemTitle());
        orderItem.setQuantity(request.quantity());
        orderItem.setUnitPrice(request.unitPrice());
        orderItem.setTotalAmount(totalAmount);
        return orderItem;
    }

    private void releaseAfterCreateFailure(CreateOrderRequestDTO request, long orderId, RuntimeException originalException) {
        try {
            inventoryClient.release(
                    request.requestId() + ":release-on-create-failure",
                    orderId,
                    request.skuId(),
                    request.quantity()
            );
        } catch (RuntimeException releaseException) {
            originalException.addSuppressed(releaseException);
        }
    }

    private OrderCreateVO returnExistingAfterDuplicateOrder(
            CreateOrderRequestDTO request,
            long orderId,
            DuplicateKeyException duplicateException
    ) {
        try {
            inventoryClient.release(
                    request.requestId() + ":release-on-duplicate-order",
                    orderId,
                    request.skuId(),
                    request.quantity()
            );
        } catch (RuntimeException releaseException) {
            duplicateException.addSuppressed(releaseException);
            throw duplicateException;
        }

        Order existingOrder = orderMapper.findByRequestId(request.requestId());
        if (existingOrder == null) {
            throw duplicateException;
        }
        return new OrderCreateVO(existingOrder.getOrderId(), existingOrder.getStatus());
    }

    private Order findExistingOrderAfterInventoryLockFailure(String requestId, RuntimeException lockFailure) {
        for (int attempt = 0; attempt < LOCK_FAILURE_DUPLICATE_REREAD_ATTEMPTS; attempt++) {
            Order existingOrder = orderMapper.findByRequestId(requestId);
            if (existingOrder != null) {
                return existingOrder;
            }
            if (attempt < LOCK_FAILURE_DUPLICATE_REREAD_ATTEMPTS - 1) {
                sleepBeforeDuplicateOrderReread(lockFailure);
            }
        }
        return null;
    }

    private void sleepBeforeDuplicateOrderReread(RuntimeException lockFailure) {
        try {
            Thread.sleep(LOCK_FAILURE_DUPLICATE_REREAD_DELAY_MILLIS);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            OrderServiceException exception = new OrderServiceException(
                    "interrupted while checking duplicate order after inventory lock failure",
                    lockFailure
            );
            exception.addSuppressed(interrupted);
            throw exception;
        }
    }

    private String defaultRequestId(String requestId, String action, Long orderId) {
        String normalized = trimToNull(requestId);
        return normalized == null ? action + ":" + orderId : normalized;
    }

    private String requireText(String value, String fieldName) {
        String normalized = trimToNull(value);
        if (normalized == null) {
            throw new OrderServiceException(fieldName + " is required");
        }
        return normalized;
    }

    private String trimToNull(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        return value.trim();
    }
}
