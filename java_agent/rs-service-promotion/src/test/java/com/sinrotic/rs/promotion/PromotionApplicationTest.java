package com.sinrotic.rs.promotion;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest(classes=PromotionApplication.class,properties={
    "spring.datasource.url=jdbc:h2:mem:promotion-startup;MODE=MySQL",
    "spring.datasource.driver-class-name=org.h2.Driver",
    "spring.cloud.nacos.discovery.enabled=false",
    "spring.cloud.discovery.enabled=false"
})
class PromotionApplicationTest {
    @Test void applicationWiresControllersAndTransactionalService() {}
}
