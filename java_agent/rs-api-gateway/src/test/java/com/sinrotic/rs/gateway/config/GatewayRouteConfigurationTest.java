package com.sinrotic.rs.gateway.config;

import org.junit.jupiter.api.Test;
import org.springframework.boot.env.YamlPropertySourceLoader;
import org.springframework.core.env.PropertySource;
import org.springframework.core.io.ClassPathResource;

import java.io.IOException;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class GatewayRouteConfigurationTest {

    @Test
    void catalogRouteTargetsCatalogService() throws IOException {
        PropertySource<?> source = new YamlPropertySourceLoader()
                .load("gateway", new ClassPathResource("application.yml"))
                .getFirst();

        assertEquals(
                "rs-service-catalog",
                source.getProperty("spring.cloud.gateway.server.webflux.routes[4].id")
        );
        assertEquals(
                "lb://rs-service-catalog",
                source.getProperty("spring.cloud.gateway.server.webflux.routes[4].uri")
        );
        assertEquals(
                "Path=/api/catalog/**",
                source.getProperty("spring.cloud.gateway.server.webflux.routes[4].predicates[0]")
        );
        assertEquals(
                "${RS_GATEWAY_AUTH_TOKEN_VALIDATION:redis}",
                source.getProperty("rs.gateway.auth.token-validation")
        );
    }

    @Test
    void commerceRoutesAreOnlyPresentInFullCommerceProfile() throws IOException {
        PropertySource<?> base = load("application.yml");
        PropertySource<?> commerce = load("application-full-commerce.yml");

        List<String> baseRoutes = routeIds(base, 20);
        List<String> commerceRoutes = routeIds(commerce, 20);
        assertTrue(baseRoutes.contains("rs-service-checkout"));
        assertTrue(baseRoutes.contains("rs-service-promotion"));
        assertTrue(commerceRoutes.contains("rs-service-checkout"));
        assertTrue(commerceRoutes.contains("rs-service-promotion"));
        assertFalse(baseRoutes.contains("rs-service-order"));
        assertFalse(baseRoutes.contains("rs-service-payment"));
        assertFalse(baseRoutes.contains("rs-service-seckill"));
        assertTrue(baseRoutes.contains("rs-service-inventory"));
        assertTrue(commerceRoutes.contains("rs-service-order"));
        assertTrue(commerceRoutes.contains("rs-service-payment"));
        assertTrue(commerceRoutes.contains("rs-service-seckill"));
        assertTrue(commerceRoutes.contains("rs-service-inventory"));
    }

    private PropertySource<?> load(String resource) throws IOException {
        return new YamlPropertySourceLoader()
                .load(resource, new ClassPathResource(resource))
                .getFirst();
    }

    private List<String> routeIds(PropertySource<?> source, int count) {
        return java.util.stream.IntStream.range(0, count)
                .mapToObj(index -> source.getProperty("spring.cloud.gateway.server.webflux.routes[" + index + "].id"))
                .filter(String.class::isInstance)
                .map(String.class::cast)
                .toList();
    }
}
