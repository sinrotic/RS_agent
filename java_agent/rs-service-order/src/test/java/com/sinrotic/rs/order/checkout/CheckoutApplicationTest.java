package com.sinrotic.rs.order.checkout;

import com.sinrotic.rs.order.OrderServiceApplication;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest(classes=OrderServiceApplication.class,properties={
    "spring.datasource.url=jdbc:h2:mem:checkout-startup;MODE=MySQL",
    "spring.datasource.driver-class-name=org.h2.Driver",
    "spring.cloud.nacos.discovery.enabled=false",
    "spring.cloud.discovery.enabled=false",
    "spring.kafka.listener.auto-startup=false",
    "spring.kafka.admin.auto-create=false",
    "rs.checkout.worker.enabled=false"
})
class CheckoutApplicationTest {
    @Test void applicationWiresCheckoutAndKafkaConsumer() {}
}
