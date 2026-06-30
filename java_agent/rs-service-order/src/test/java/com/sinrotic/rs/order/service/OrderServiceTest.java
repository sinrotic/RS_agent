package com.sinrotic.rs.order.service;

import com.sinrotic.rs.order.client.InventoryClient;
import com.sinrotic.rs.order.domain.dto.CreateOrderRequestDTO;
import com.sinrotic.rs.order.domain.dto.OrderPaidRequestDTO;
import com.sinrotic.rs.order.domain.dto.SeckillOrderCreateMessageDTO;
import com.sinrotic.rs.order.domain.entity.Order;
import com.sinrotic.rs.order.domain.entity.OrderItem;
import com.sinrotic.rs.order.domain.vo.OrderCreateVO;
import com.sinrotic.rs.order.mapper.OrderItemMapper;
import com.sinrotic.rs.order.mapper.OrderMapper;
import com.sinrotic.rs.order.service.seckill.ConfiguredSeckillOrderItemResolver;
import com.sinrotic.rs.order.service.seckill.SeckillActivityProperties;
import com.sinrotic.rs.order.service.seckill.SeckillOrderItemResolver;
import com.sinrotic.rs.order.service.seckill.SeckillOrderItemSnapshot;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.NullSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.InOrder;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.transaction.annotation.Transactional;

import java.lang.reflect.Method;
import java.util.concurrent.atomic.AtomicLong;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class OrderServiceTest {

    private OrderMapper orderMapper;
    private OrderItemMapper orderItemMapper;
    private InventoryClient inventoryClient;
    private SeckillOrderItemResolver seckillOrderItemResolver;
    private OrderService orderService;

    @BeforeEach
    void setUp() {
        orderMapper = mock(OrderMapper.class);
        orderItemMapper = mock(OrderItemMapper.class);
        inventoryClient = mock(InventoryClient.class);
        seckillOrderItemResolver = mock(SeckillOrderItemResolver.class);
        AtomicLong idSequence = new AtomicLong(1000L);
        OrderCreationTransactionService orderCreationTransactionService =
                new OrderCreationTransactionService(orderMapper, orderItemMapper);
        OrderStateTransitionService orderStateTransitionService =
                new OrderStateTransitionService(orderMapper, orderItemMapper);
        orderService = new OrderService(
                orderMapper,
                orderCreationTransactionService,
                orderStateTransitionService,
                inventoryClient,
                idSequence::incrementAndGet,
                seckillOrderItemResolver
        );
    }

    @Test
    void createOrderIsNotTransactional() throws NoSuchMethodException {
        Method createOrder = OrderService.class.getMethod("createOrder", CreateOrderRequestDTO.class);

        assertNull(createOrder.getAnnotation(Transactional.class));
    }

    @Test
    void createOrderRowsIsTransactional() throws NoSuchMethodException {
        Method createOrderRows = OrderCreationTransactionService.class.getMethod(
                "createOrderRows",
                Order.class,
                OrderItem.class
        );
        Transactional transactional = createOrderRows.getAnnotation(Transactional.class);

        assertNotNull(transactional);
        assertEquals(1, transactional.rollbackFor().length);
        assertSame(Exception.class, transactional.rollbackFor()[0]);
    }

    @Test
    void createOrderLocksInventoryThenInsertsAndReturnsWaitingPayment() {
        CreateOrderRequestDTO request = createRequest("req-1");
        when(orderMapper.findByRequestId("req-1")).thenReturn(null);
        when(orderMapper.insertOrder(any(Order.class))).thenReturn(1);
        when(orderItemMapper.insertItem(any(OrderItem.class))).thenReturn(1);

        OrderCreateVO response = orderService.createOrder(request);

        assertEquals(1001L, response.orderId());
        assertEquals("WAITING_PAYMENT", response.status());
        InOrder inOrder = inOrder(inventoryClient, orderMapper, orderItemMapper);
        inOrder.verify(inventoryClient).lock("req-1", 1001L, "sku-1", 2);
        inOrder.verify(orderMapper).insertOrder(any(Order.class));
        inOrder.verify(orderItemMapper).insertItem(any(OrderItem.class));
    }

    @Test
    void createOrderReturnsExistingOrderWithoutLockingAgain() {
        when(orderMapper.findByRequestId("req-1")).thenReturn(order(88L, "req-1", "WAITING_PAYMENT"));

        OrderCreateVO response = orderService.createOrder(createRequest("req-1"));

        assertEquals(88L, response.orderId());
        assertEquals("WAITING_PAYMENT", response.status());
        verify(inventoryClient, never()).lock(any(), any(), any(), any());
        verify(orderMapper, never()).insertOrder(any());
        verify(orderItemMapper, never()).insertItem(any());
    }

    @Test
    void createSeckillOrderUsesResolvedItemTitleAndPrice() {
        SeckillOrderCreateMessageDTO message = new SeckillOrderCreateMessageDTO(
                "sec-req-1",
                1L,
                "activity-1",
                "item-9",
                "sku-9",
                3
        );
        when(seckillOrderItemResolver.resolve("activity-1", "item-9", "sku-9"))
                .thenReturn(new SeckillOrderItemSnapshot("confirmed-item-9", "Flash Deal SKU 9", 199L));
        when(orderMapper.findByRequestId("sec-req-1")).thenReturn(null);
        when(orderMapper.insertOrder(any(Order.class))).thenReturn(1);
        when(orderItemMapper.insertItem(any(OrderItem.class))).thenReturn(1);

        OrderCreateVO response = orderService.createSeckillOrder(message);

        assertEquals(1001L, response.orderId());
        assertEquals("WAITING_PAYMENT", response.status());
        verify(inventoryClient).lock("sec-req-1", 1001L, "sku-9", 3);
        verify(orderMapper).insertOrder(org.mockito.ArgumentMatchers.argThat(order ->
                order.getRequestId().equals("sec-req-1")
                        && order.getAccountId().equals(1L)
                        && order.getProfileUserId() == null
                        && order.getSessionId() == null
                        && order.getRecommendRequestId() == null
                        && order.getTotalAmount().equals(597L)
        ));
        verify(orderItemMapper).insertItem(org.mockito.ArgumentMatchers.argThat(item ->
                item.getItemId().equals("confirmed-item-9")
                        && item.getSkuId().equals("sku-9")
                        && item.getItemTitle().equals("Flash Deal SKU 9")
                        && item.getQuantity().equals(3)
                        && item.getUnitPrice().equals(199L)
                        && item.getTotalAmount().equals(597L)
        ));
    }

    @Test
    void createSeckillOrderWithConfiguredActivityItemAndSkuWritesResolvedItemSnapshot() {
        SeckillActivityProperties properties = seckillProperties("activity-1", "item-9", "sku-9", "Flash Deal SKU 9", 199L);
        OrderService serviceWithConfiguredResolver = orderServiceWithConfiguredResolver(properties);
        SeckillOrderCreateMessageDTO message = new SeckillOrderCreateMessageDTO(
                "sec-req-configured",
                1L,
                "activity-1",
                "item-9",
                "sku-9",
                3
        );
        when(orderMapper.findByRequestId("sec-req-configured")).thenReturn(null);
        when(orderMapper.insertOrder(any(Order.class))).thenReturn(1);
        when(orderItemMapper.insertItem(any(OrderItem.class))).thenReturn(1);

        OrderCreateVO response = serviceWithConfiguredResolver.createSeckillOrder(message);

        assertEquals(1001L, response.orderId());
        assertEquals("WAITING_PAYMENT", response.status());
        verify(inventoryClient).lock("sec-req-configured", 1001L, "sku-9", 3);
        verify(orderMapper).insertOrder(org.mockito.ArgumentMatchers.argThat(order ->
                order.getRequestId().equals("sec-req-configured")
                        && order.getAccountId().equals(1L)
                        && order.getTotalAmount().equals(597L)
        ));
        verify(orderItemMapper).insertItem(org.mockito.ArgumentMatchers.argThat(item ->
                item.getItemId().equals("item-9")
                        && item.getSkuId().equals("sku-9")
                        && item.getItemTitle().equals("Flash Deal SKU 9")
                        && item.getQuantity().equals(3)
                        && item.getUnitPrice().equals(199L)
                        && item.getTotalAmount().equals(597L)
        ));
    }

    @Test
    void createSeckillOrderReturnsExistingOrderForDuplicateRequestId() {
        SeckillOrderCreateMessageDTO message = new SeckillOrderCreateMessageDTO(
                "sec-req-1",
                1L,
                "activity-1",
                "item-9",
                "sku-9",
                3
        );
        when(orderMapper.findByRequestId("sec-req-1")).thenReturn(order(88L, "sec-req-1", "WAITING_PAYMENT"));

        OrderCreateVO response = orderService.createSeckillOrder(message);

        assertEquals(88L, response.orderId());
        assertEquals("WAITING_PAYMENT", response.status());
        verify(seckillOrderItemResolver, never()).resolve(any(), any(), any());
        verify(inventoryClient, never()).lock(any(), any(), any(), any());
        verify(orderMapper, never()).insertOrder(any());
        verify(orderItemMapper, never()).insertItem(any());
    }

    @Test
    void createSeckillOrderThrowsWhenConfiguredResolverCannotFindItemWithoutLockingOrInserting() {
        OrderService serviceWithConfiguredResolver = new OrderService(
                orderMapper,
                new OrderCreationTransactionService(orderMapper, orderItemMapper),
                new OrderStateTransitionService(orderMapper, orderItemMapper),
                inventoryClient,
                new AtomicLong(1000L)::incrementAndGet,
                new ConfiguredSeckillOrderItemResolver(new SeckillActivityProperties())
        );
        SeckillOrderCreateMessageDTO message = new SeckillOrderCreateMessageDTO(
                "sec-req-missing",
                1L,
                "missing-activity",
                "item-9",
                "sku-9",
                3
        );
        when(orderMapper.findByRequestId("sec-req-missing")).thenReturn(null);

        assertThrows(OrderServiceException.class, () -> serviceWithConfiguredResolver.createSeckillOrder(message));

        verify(inventoryClient, never()).lock(any(), any(), any(), any());
        verify(orderMapper, never()).insertOrder(any());
        verify(orderItemMapper, never()).insertItem(any());
    }

    @Test
    void createSeckillOrderRejectsMismatchedConfiguredItemAndSkuWithoutLockingOrInserting() {
        SeckillActivityProperties properties = seckillProperties("activity-1", "item-9", "sku-9", "Flash Deal SKU 9", 199L);
        OrderService serviceWithConfiguredResolver = orderServiceWithConfiguredResolver(properties);
        SeckillOrderCreateMessageDTO message = new SeckillOrderCreateMessageDTO(
                "sec-req-mismatch",
                1L,
                "activity-1",
                "wrong-item",
                "sku-9",
                3
        );
        when(orderMapper.findByRequestId("sec-req-mismatch")).thenReturn(null);

        assertThrows(OrderServiceException.class, () -> serviceWithConfiguredResolver.createSeckillOrder(message));

        verify(inventoryClient, never()).lock(any(), any(), any(), any());
        verify(orderMapper, never()).insertOrder(any());
        verify(orderItemMapper, never()).insertItem(any());
    }

    @Test
    void createSeckillOrderRejectsMissingConfiguredSkuWithoutLockingOrInserting() {
        SeckillActivityProperties properties = seckillProperties("activity-1", "item-9", "sku-9", "Flash Deal SKU 9", 199L);
        OrderService serviceWithConfiguredResolver = orderServiceWithConfiguredResolver(properties);
        SeckillOrderCreateMessageDTO message = new SeckillOrderCreateMessageDTO(
                "sec-req-missing-sku",
                1L,
                "activity-1",
                "item-9",
                "missing-sku",
                3
        );
        when(orderMapper.findByRequestId("sec-req-missing-sku")).thenReturn(null);

        assertThrows(OrderServiceException.class, () -> serviceWithConfiguredResolver.createSeckillOrder(message));

        verify(inventoryClient, never()).lock(any(), any(), any(), any());
        verify(orderMapper, never()).insertOrder(any());
        verify(orderItemMapper, never()).insertItem(any());
    }

    @Test
    void createOrderReturnsExistingOrderWhenInventoryLockFailsAfterDuplicateRequestWins() {
        CreateOrderRequestDTO request = createRequest("req-1");
        RuntimeException lockFailure = new RuntimeException("request_id already used for another order");
        when(orderMapper.findByRequestId("req-1"))
                .thenReturn(null)
                .thenReturn(order(88L, "req-1", "WAITING_PAYMENT"));
        org.mockito.Mockito.doThrow(lockFailure)
                .when(inventoryClient).lock("req-1", 1001L, "sku-1", 2);

        OrderCreateVO response = orderService.createOrder(request);

        assertEquals(88L, response.orderId());
        assertEquals("WAITING_PAYMENT", response.status());
        verify(orderMapper, never()).insertOrder(any());
        verify(orderItemMapper, never()).insertItem(any());
    }

    @Test
    void createOrderRethrowsInventoryLockFailureWhenDuplicateOrderDoesNotAppear() {
        CreateOrderRequestDTO request = createRequest("req-1");
        RuntimeException lockFailure = new RuntimeException("inventory lock failed");
        when(orderMapper.findByRequestId("req-1")).thenReturn(null);
        org.mockito.Mockito.doThrow(lockFailure)
                .when(inventoryClient).lock("req-1", 1001L, "sku-1", 2);

        RuntimeException thrown = assertThrows(RuntimeException.class, () -> orderService.createOrder(request));

        assertSame(lockFailure, thrown);
        verify(orderMapper, times(4)).findByRequestId("req-1");
        verify(orderMapper, never()).insertOrder(any());
        verify(orderItemMapper, never()).insertItem(any());
    }

    @Test
    void createOrderRestoresInterruptWhenDuplicateOrderRetrySleepIsInterrupted() {
        CreateOrderRequestDTO request = createRequest("req-1");
        RuntimeException lockFailure = new RuntimeException("inventory lock failed");
        when(orderMapper.findByRequestId("req-1")).thenReturn(null);
        org.mockito.Mockito.doThrow(lockFailure)
                .when(inventoryClient).lock("req-1", 1001L, "sku-1", 2);

        Thread.currentThread().interrupt();
        try {
            OrderServiceException thrown = assertThrows(OrderServiceException.class, () -> orderService.createOrder(request));

            assertSame(lockFailure, thrown.getCause());
            assertEquals(true, Thread.currentThread().isInterrupted());
        } finally {
            Thread.interrupted();
        }
    }

    @Test
    void createOrderReleasesInventoryWhenLocalInsertFailsAfterLock() {
        CreateOrderRequestDTO request = createRequest("req-1");
        RuntimeException insertFailure = new RuntimeException("insert failed");
        when(orderMapper.findByRequestId("req-1")).thenReturn(null);
        when(orderMapper.insertOrder(any(Order.class))).thenThrow(insertFailure);

        RuntimeException thrown = assertThrows(RuntimeException.class, () -> orderService.createOrder(request));

        assertEquals(insertFailure, thrown);
        verify(inventoryClient).lock("req-1", 1001L, "sku-1", 2);
        verify(inventoryClient).release("req-1:release-on-create-failure", 1001L, "sku-1", 2);
    }

    @Test
    void createOrderDuplicateRequestIdAfterLockReleasesLoserAndReturnsExistingOrder() {
        CreateOrderRequestDTO request = createRequest("req-1");
        DuplicateKeyException duplicate = new DuplicateKeyException("duplicate request_id");
        when(orderMapper.findByRequestId("req-1"))
                .thenReturn(null)
                .thenReturn(order(88L, "req-1", "WAITING_PAYMENT"));
        when(orderMapper.insertOrder(any(Order.class))).thenThrow(duplicate);

        OrderCreateVO response = orderService.createOrder(request);

        assertEquals(88L, response.orderId());
        assertEquals("WAITING_PAYMENT", response.status());
        InOrder inOrder = inOrder(inventoryClient, orderMapper, orderItemMapper);
        inOrder.verify(inventoryClient).lock("req-1", 1001L, "sku-1", 2);
        inOrder.verify(orderMapper).insertOrder(any(Order.class));
        inOrder.verify(inventoryClient).release("req-1:release-on-duplicate-order", 1001L, "sku-1", 2);
        inOrder.verify(orderMapper).findByRequestId("req-1");
        verify(orderItemMapper, never()).insertItem(any());
    }

    @Test
    void createOrderDuplicateRequestIdReleaseFailureThrowsDuplicateWithSuppressedReleaseFailure() {
        CreateOrderRequestDTO request = createRequest("req-1");
        DuplicateKeyException duplicate = new DuplicateKeyException("duplicate request_id");
        RuntimeException releaseFailure = new RuntimeException("release failed");
        when(orderMapper.findByRequestId("req-1")).thenReturn(null);
        when(orderMapper.insertOrder(any(Order.class))).thenThrow(duplicate);
        org.mockito.Mockito.doThrow(releaseFailure)
                .when(inventoryClient).release("req-1:release-on-duplicate-order", 1001L, "sku-1", 2);

        DuplicateKeyException thrown = assertThrows(DuplicateKeyException.class, () -> orderService.createOrder(request));

        assertSame(duplicate, thrown);
        assertEquals(1, thrown.getSuppressed().length);
        assertSame(releaseFailure, thrown.getSuppressed()[0]);
        verify(orderMapper, times(1)).findByRequestId("req-1");
    }

    @Test
    void createOrderLocalInsertFailureReleaseFailureThrowsOriginalWithSuppressedReleaseFailure() {
        CreateOrderRequestDTO request = createRequest("req-1");
        RuntimeException insertFailure = new RuntimeException("insert failed");
        RuntimeException releaseFailure = new RuntimeException("release failed");
        when(orderMapper.findByRequestId("req-1")).thenReturn(null);
        when(orderMapper.insertOrder(any(Order.class))).thenThrow(insertFailure);
        org.mockito.Mockito.doThrow(releaseFailure)
                .when(inventoryClient).release("req-1:release-on-create-failure", 1001L, "sku-1", 2);

        RuntimeException thrown = assertThrows(RuntimeException.class, () -> orderService.createOrder(request));

        assertSame(insertFailure, thrown);
        assertEquals(1, thrown.getSuppressed().length);
        assertSame(releaseFailure, thrown.getSuppressed()[0]);
    }

    @Test
    void markPaidConfirmsInventoryWhenOrderTransitionsToPaid() {
        when(orderMapper.markPaid(10L)).thenReturn(1);
        when(orderItemMapper.findByOrderId(10L)).thenReturn(orderItem(10L, "sku-1", 2));

        orderService.markPaid(new OrderPaidRequestDTO("paid-req-1", 10L, "mockpay", "tx-1"));

        verify(inventoryClient).confirm("paid-req-1", 10L, "sku-1", 2);
    }

    @Test
    void markPaidLoadsTransitionBeforeConfirmingInventory() {
        when(orderMapper.markPaid(10L)).thenReturn(1);
        when(orderItemMapper.findByOrderId(10L)).thenReturn(orderItem(10L, "sku-1", 2));

        orderService.markPaid(new OrderPaidRequestDTO("paid-req-1", 10L, "mockpay", "tx-1"));

        InOrder inOrder = inOrder(orderMapper, orderItemMapper, inventoryClient);
        inOrder.verify(orderMapper).markPaid(10L);
        inOrder.verify(orderItemMapper).findByOrderId(10L);
        inOrder.verify(inventoryClient).confirm("paid-req-1", 10L, "sku-1", 2);
    }

    @Test
    void markPaidDoesNotConfirmInventoryWhenOrderDidNotTransition() {
        when(orderMapper.markPaid(10L)).thenReturn(0);

        orderService.markPaid(new OrderPaidRequestDTO("paid-req-1", 10L, "mockpay", "tx-1"));

        verify(orderItemMapper, never()).findByOrderId(any());
        verify(inventoryClient, never()).confirm(any(), any(), any(), any());
    }

    @ParameterizedTest
    @NullSource
    @ValueSource(strings = {"", "   "})
    void closeTimeoutReleasesInventoryWithDefaultRequestIdWhenMissing(String requestId) {
        when(orderMapper.closeTimeout(10L)).thenReturn(1);
        when(orderItemMapper.findByOrderId(10L)).thenReturn(orderItem(10L, "sku-1", 2));

        orderService.closeTimeout(10L, requestId);

        InOrder inOrder = inOrder(orderMapper, orderItemMapper, inventoryClient);
        inOrder.verify(orderMapper).closeTimeout(10L);
        inOrder.verify(orderItemMapper).findByOrderId(10L);
        inOrder.verify(inventoryClient).release("close-timeout:10", 10L, "sku-1", 2);
        verify(inventoryClient).release("close-timeout:10", 10L, "sku-1", 2);
    }

    @ParameterizedTest
    @NullSource
    @ValueSource(strings = {"", "   "})
    void cancelReleasesInventoryWithDefaultRequestIdWhenMissing(String requestId) {
        when(orderMapper.cancel(10L)).thenReturn(1);
        when(orderItemMapper.findByOrderId(10L)).thenReturn(orderItem(10L, "sku-1", 2));

        orderService.cancel(10L, requestId);

        InOrder inOrder = inOrder(orderMapper, orderItemMapper, inventoryClient);
        inOrder.verify(orderMapper).cancel(10L);
        inOrder.verify(orderItemMapper).findByOrderId(10L);
        inOrder.verify(inventoryClient).release("cancel:10", 10L, "sku-1", 2);
        verify(inventoryClient).release("cancel:10", 10L, "sku-1", 2);
    }

    @Test
    void closeTimeoutDoesNotLoadItemOrReleaseInventoryWhenOrderDidNotTransition() {
        when(orderMapper.closeTimeout(10L)).thenReturn(0);

        orderService.closeTimeout(10L, null);

        verify(orderItemMapper, never()).findByOrderId(any());
        verify(inventoryClient, never()).release(any(), any(), any(), any());
    }

    @Test
    void cancelDoesNotLoadItemOrReleaseInventoryWhenOrderDidNotTransition() {
        when(orderMapper.cancel(10L)).thenReturn(0);

        orderService.cancel(10L, null);

        verify(orderItemMapper, never()).findByOrderId(any());
        verify(inventoryClient, never()).release(any(), any(), any(), any());
    }

    private CreateOrderRequestDTO createRequest(String requestId) {
        return new CreateOrderRequestDTO(
                requestId,
                1L,
                "profile-1",
                "session-1",
                "rec-1",
                "item-1",
                "sku-1",
                "Item One",
                2,
                150L
        );
    }

    private Order order(Long orderId, String requestId, String status) {
        Order order = new Order();
        order.setOrderId(orderId);
        order.setRequestId(requestId);
        order.setAccountId(1L);
        order.setStatus(status);
        order.setTotalAmount(300L);
        return order;
    }

    private OrderItem orderItem(Long orderId, String skuId, Integer quantity) {
        OrderItem orderItem = new OrderItem();
        orderItem.setOrderId(orderId);
        orderItem.setItemId("item-1");
        orderItem.setSkuId(skuId);
        orderItem.setItemTitle("Item One");
        orderItem.setQuantity(quantity);
        orderItem.setUnitPrice(150L);
        orderItem.setTotalAmount(300L);
        return orderItem;
    }

    private OrderService orderServiceWithConfiguredResolver(SeckillActivityProperties properties) {
        return new OrderService(
                orderMapper,
                new OrderCreationTransactionService(orderMapper, orderItemMapper),
                new OrderStateTransitionService(orderMapper, orderItemMapper),
                inventoryClient,
                new AtomicLong(1000L)::incrementAndGet,
                new ConfiguredSeckillOrderItemResolver(properties)
        );
    }

    private SeckillActivityProperties seckillProperties(
            String activityId,
            String itemId,
            String skuId,
            String itemTitle,
            Long unitPrice
    ) {
        SeckillActivityProperties properties = new SeckillActivityProperties();
        SeckillActivityProperties.Activity activity = new SeckillActivityProperties.Activity();
        SeckillActivityProperties.Item item = new SeckillActivityProperties.Item();
        SeckillActivityProperties.Sku sku = new SeckillActivityProperties.Sku();
        sku.setItemTitle(itemTitle);
        sku.setUnitPrice(unitPrice);
        item.getSkus().put(skuId, sku);
        activity.getItems().put(itemId, item);
        properties.getActivities().put(activityId, activity);
        return properties;
    }
}
