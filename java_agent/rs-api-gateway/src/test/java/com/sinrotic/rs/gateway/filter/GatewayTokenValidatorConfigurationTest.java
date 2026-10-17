package com.sinrotic.rs.gateway.filter;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.data.redis.core.ReactiveStringRedisTemplate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

class GatewayTokenValidatorConfigurationTest {

    private final ApplicationContextRunner contextRunner = new ApplicationContextRunner()
            .withBean(ReactiveStringRedisTemplate.class, () -> mock(ReactiveStringRedisTemplate.class))
            .withUserConfiguration(PresenceGatewayTokenValidator.class, RedisGatewayTokenValidator.class);

    @Test
    void presenceModeRegistersOnlyPresenceValidator() {
        contextRunner
                .withPropertyValues("rs.gateway.auth.token-validation=presence")
                .run(context -> {
                    assertThat(context).hasSingleBean(GatewayTokenValidator.class);
                    assertThat(context).hasSingleBean(PresenceGatewayTokenValidator.class);
                    assertThat(context).doesNotHaveBean(RedisGatewayTokenValidator.class);
                });
    }

    @Test
    void redisModeRegistersOnlyRedisValidator() {
        contextRunner
                .withPropertyValues("rs.gateway.auth.token-validation=redis")
                .run(context -> {
                    assertThat(context).hasSingleBean(GatewayTokenValidator.class);
                    assertThat(context).hasSingleBean(RedisGatewayTokenValidator.class);
                    assertThat(context).doesNotHaveBean(PresenceGatewayTokenValidator.class);
                });
    }

    @Test
    void invalidModeRegistersNoValidator() {
        contextRunner
                .withPropertyValues("rs.gateway.auth.token-validation=invalid")
                .run(context -> assertThat(context).doesNotHaveBean(GatewayTokenValidator.class));
    }
}
