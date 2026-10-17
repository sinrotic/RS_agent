package com.sinrotic.rs.payment.service;

import com.sinrotic.rs.payment.client.OrderClient;
import com.sinrotic.rs.payment.mapper.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mybatis.spring.SqlSessionFactoryBean;
import org.mybatis.spring.SqlSessionTemplate;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.support.PathMatchingResourcePatternResolver;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.http.HttpStatus;
import java.util.UUID;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class PaymentNotificationPersistenceTest {
    JdbcTemplate jdbc;
    TransactionTemplate transaction;
    PaymentNotificationMapper notifications;
    PaymentTransitionService transitions;
    PaymentOrderMapper payments;
    PaymentCallbackMapper callbacks;
    DataSourceTransactionManager manager;
    OrderClient order;

    @BeforeEach
    void setup() throws Exception {
        var ds = new DriverManagerDataSource("jdbc:h2:mem:" + UUID.randomUUID() + ";MODE=MySQL;DB_CLOSE_DELAY=-1", "sa", "");
        new ResourceDatabasePopulator(new FileSystemResource("../sql/rs_service_trade_schema.sql"),
                new FileSystemResource("../sql/rs_service_commerce_v1_schema.sql")).execute(ds);
        jdbc = new JdbcTemplate(ds);
        manager = new DataSourceTransactionManager(ds);
        transaction = new TransactionTemplate(manager);
        var factory = new SqlSessionFactoryBean();
        factory.setDataSource(ds);
        var configuration = new org.apache.ibatis.session.Configuration();
        configuration.setMapUnderscoreToCamelCase(true);
        factory.setConfiguration(configuration);
        factory.setMapperLocations(new PathMatchingResourcePatternResolver().getResources("classpath:mapper/*.xml"));
        var session = new SqlSessionTemplate(factory.getObject());
        notifications = session.getMapper(PaymentNotificationMapper.class);
        payments = session.getMapper(PaymentOrderMapper.class);
        callbacks = session.getMapper(PaymentCallbackMapper.class);
        transitions = transactional(new PaymentTransitionService(payments, callbacks, notifications));
        order = mock(OrderClient.class);
        jdbc.update("INSERT INTO payment_orders(payment_id,order_id,provider,status,amount) VALUES (1,10,'mock','WAITING_PAY',500)");
    }

    PaymentTransitionService transactional(PaymentTransitionService service) {
        var proxy = new org.springframework.aop.framework.ProxyFactory(service);
        proxy.addAdvice(new org.springframework.transaction.interceptor.TransactionInterceptor(manager,
                new org.springframework.transaction.annotation.AnnotationTransactionAttributeSource()));
        return (PaymentTransitionService) proxy.getProxy();
    }

    void paid() { transitions.recordPaidCallback("mock", "tx", 10L, 500L, "hash"); }
    String state() { return jdbc.queryForObject("SELECT status FROM payment_order_notifications WHERE order_id=10", String.class); }

    @Test
    void reviewCanBeResumedWithAuditAndTheOriginalPaymentTransaction() {
        paid();doThrow(new HttpClientErrorException(HttpStatus.CONFLICT)).when(order).markPaid(10L,"mock","tx");
        new PaymentNotificationService(notifications,order).dispatch(10L);
        var ops=new PaymentOperationsService(jdbc,manager,false);
        assertThat(ops.summary()).containsEntry("reviewRequired",1L);
        assertThat(ops.tasks(1200)).hasSize(1);
        ops.retry(10L,new PaymentOperationsService.OperatorAction("operator","订单金额和支付流水已核对"));
        assertThat(state()).isEqualTo("PENDING");
        doNothing().when(order).markPaid(10L,"mock","tx");
        new PaymentNotificationService(notifications,order).processPending();
        assertThat(state()).isEqualTo("DONE");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM commerce_operation_audit",Integer.class)).isOne();
        verify(order,times(2)).markPaid(10L,"mock","tx");
    }

    @Test
    void mockRefundIsDisabledByDefaultRestrictedToMockAndIdempotent() {
        paid();jdbc.update("UPDATE payment_order_notifications SET status='REVIEW' WHERE order_id=10");
        var action=new PaymentOperationsService.OperatorAction("operator","模拟支付后订单关闭，验证退款分支");
        assertThatThrownBy(()->new PaymentOperationsService(jdbc,manager,false).mockRefund(10L,action))
                .isInstanceOfSatisfying(org.springframework.web.server.ResponseStatusException.class,e->assertThat(e.getStatusCode().value()).isEqualTo(404));
        var ops=new PaymentOperationsService(jdbc,manager,true);
        jdbc.update("UPDATE payment_orders SET provider='real' WHERE order_id=10");
        assertThatThrownBy(()->ops.mockRefund(10L,action)).isInstanceOf(org.springframework.web.server.ResponseStatusException.class);
        assertThat(state()).isEqualTo("REVIEW");
        jdbc.update("UPDATE payment_orders SET provider='mock' WHERE order_id=10");
        assertThat(ops.mockRefund(10L,action).moneyMoved()).isFalse();
        assertThat(ops.mockRefund(10L,action).mock()).isTrue();
        assertThat(state()).isEqualTo("MOCK_REFUNDED");
        assertThat(notifications.dueOrderIds()).isEmpty();
        assertThat(jdbc.queryForObject("SELECT status FROM payment_orders WHERE order_id=10",String.class)).isEqualTo("PAID");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM commerce_operation_audit",Integer.class)).isOne();
        new ResourceDatabasePopulator(new FileSystemResource("../sql/rs_service_trade_schema.sql"),
                new FileSystemResource("../sql/rs_service_commerce_v1_schema.sql")).execute(jdbc.getDataSource());
        assertThat(state()).isEqualTo("MOCK_REFUNDED");
        assertThatThrownBy(()->ops.retry(10L,action)).isInstanceOf(org.springframework.web.server.ResponseStatusException.class);
    }

    @Test
    void transientNotificationStopsAtBudgetAndFailedAuditCannotResume() {
        paid();doThrow(new IllegalStateException("network down")).when(order).markPaid(10L,"mock","tx");
        new PaymentNotificationService(notifications,order,1).dispatch(10L);
        assertThat(state()).isEqualTo("REVIEW");
        jdbc.execute("DROP TABLE commerce_operation_audit");
        assertThatThrownBy(()->new PaymentOperationsService(jdbc,manager,false).retry(10L,
                new PaymentOperationsService.OperatorAction("operator","恢复服务后重试"))).isInstanceOf(RuntimeException.class);
        assertThat(state()).isEqualTo("REVIEW");
    }

    @Test
    void failedHttpNotificationSurvivesServiceRestartAndCompletesWithoutAnotherCallback() {
        paid();
        doThrow(new IllegalStateException("network_down")).doNothing().when(order).markPaid(10L, "mock", "tx");
        new PaymentNotificationService(notifications, order).dispatch(10L);
        assertThat(state()).isEqualTo("PENDING");
        assertThat(jdbc.queryForObject("SELECT status FROM payment_orders WHERE order_id=10", String.class)).isEqualTo("PAID");
        jdbc.update("UPDATE payment_order_notifications SET next_attempt_at=TIMESTAMPADD(SECOND,-1,CURRENT_TIMESTAMP)");
        new PaymentNotificationService(notifications, order).processPending();
        assertThat(state()).isEqualTo("DONE");
        paid();
        new PaymentNotificationService(notifications, order).processPending();
        assertThat(state()).isEqualTo("DONE");
        verify(order, times(2)).markPaid(10L, "mock", "tx");
    }

    @Test
    void rollbackCannotLeavePaidWithoutItsOutboxRecord() {
        assertThatThrownBy(() -> transaction.executeWithoutResult(status -> {
            transitions.recordPaidCallback("mock", "tx", 10L, 500L, "hash");
            throw new IllegalStateException("rollback");
        })).isInstanceOf(IllegalStateException.class);
        assertThat(jdbc.queryForObject("SELECT status FROM payment_orders WHERE order_id=10", String.class)).isEqualTo("WAITING_PAY");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM payment_order_notifications", Integer.class)).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM payment_callbacks", Integer.class)).isZero();
    }

    @Test
    void failedOutboxInsertRollsBackTheActualAnnotatedTransition() {
        var broken = mock(PaymentNotificationMapper.class);
        doThrow(new IllegalStateException("outbox_insert_failure")).when(broken).enqueue(10L,"mock","tx");
        var service = transactional(new PaymentTransitionService(payments,callbacks,broken));
        assertThatThrownBy(() -> service.recordPaidCallback("mock","tx",10L,500L,"hash"))
                .isInstanceOf(IllegalStateException.class);
        assertThat(jdbc.queryForObject("SELECT status FROM payment_orders WHERE order_id=10", String.class)).isEqualTo("WAITING_PAY");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM payment_callbacks", Integer.class)).isZero();
    }

    @Test
    void expiredClaimCanRecoverButOldWorkerCannotCompleteNewClaim() {
        paid();
        assertThat(notifications.claim(10L, "old-worker")).isEqualTo(1);
        assertThat(notifications.claim(10L, "second-worker")).isZero();
        jdbc.update("UPDATE payment_order_notifications SET lease_until=TIMESTAMPADD(SECOND,-1,CURRENT_TIMESTAMP)");
        assertThat(notifications.claim(10L, "new-worker")).isEqualTo(1);
        assertThat(notifications.complete(10L, "old-worker")).isZero();
        assertThat(notifications.complete(10L, "new-worker")).isEqualTo(1);
    }

    @Test
    void closedOrderRequiresReviewAndRepeatedMigrationPreservesThatState() {
        paid();
        doThrow(new HttpClientErrorException(HttpStatus.CONFLICT)).when(order).markPaid(10L, "mock", "tx");
        new PaymentNotificationService(notifications, order).dispatch(10L);
        assertThat(state()).isEqualTo("REVIEW");
        new ResourceDatabasePopulator(new FileSystemResource("../sql/rs_service_trade_schema.sql")).execute(jdbc.getDataSource());
        assertThat(state()).isEqualTo("REVIEW");
        assertThat(notifications.dueOrderIds()).isEmpty();
    }
}
