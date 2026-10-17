package com.sinrotic.rs.model;

import com.sinrotic.rs.model.service.ModelGatewayService;
import com.sinrotic.rs.model.service.ModelHealthService;
import com.sinrotic.rs.model.service.impl.HttpModelGatewayService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.ApplicationContext;
import org.springframework.web.client.RestClient;

import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.NONE, properties = {
        "spring.cloud.discovery.enabled=false",
        "spring.cloud.nacos.discovery.enabled=false",
        "rs.model.runtime.embedding-base-url=",
        "rs.model.runtime.rerank-base-url="
})
class ModelServiceApplicationTest {
    @Autowired
    ApplicationContext context;

    @Test
    void defaultApplicationStartsWithRealHttpClientWithoutTestProvidedBeans() {
        assertNotNull(context.getBean(RestClient.Builder.class));
        assertInstanceOf(HttpModelGatewayService.class, context.getBean(ModelGatewayService.class));
        assertEquals("DOWN", context.getBean(ModelHealthService.class).getHealth().status());
    }
}
