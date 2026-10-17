package com.sinrotic.rs.seckill.service;

import com.sinrotic.rs.seckill.SeckillServiceApplication;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest(classes=SeckillServiceApplication.class,properties={
    "spring.datasource.url=jdbc:h2:mem:seckill-startup;MODE=MySQL",
    "spring.datasource.driver-class-name=org.h2.Driver",
    "spring.cloud.nacos.discovery.enabled=false",
    "spring.cloud.discovery.enabled=false",
    "spring.kafka.admin.auto-create=false",
    "rs.seckill.worker.enabled=false"
    ,"rs.commerce.kafka-monitor.enabled=false"
})
class SeckillApplicationTest {
    @Test void applicationWiresDurableIntakeAndKafkaProducer() {}
}
