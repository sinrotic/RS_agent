package com.sinrotic.rs.gateway.config;

import org.junit.jupiter.api.Test;
import org.springframework.boot.env.YamlPropertySourceLoader;
import org.springframework.core.env.PropertySource;
import org.springframework.core.io.ClassPathResource;

import java.io.IOException;

import static org.junit.jupiter.api.Assertions.assertEquals;

class GatewayRouteConfigurationTest {

    @Test
    void catalogRouteTargetsCatalogService() throws IOException {
        PropertySource<?> source = new YamlPropertySourceLoader()
                .load("gateway", new ClassPathResource("application.yml"))
                .getFirst();

        assertEquals(
                "rs-service-catalog",
                source.getProperty("spring.cloud.gateway.server.webflux.routes[2].id")
        );
        assertEquals(
                "lb://rs-service-catalog",
                source.getProperty("spring.cloud.gateway.server.webflux.routes[2].uri")
        );
        assertEquals(
                "Path=/api/catalog/**",
                source.getProperty("spring.cloud.gateway.server.webflux.routes[2].predicates[0]")
        );
    }
}
