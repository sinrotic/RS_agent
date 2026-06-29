package com.sinrotic.rs.platformtrace.config;

import com.sinrotic.rs.platformtrace.service.client.HttpPlatformTraceDownstreamClient;
import com.sinrotic.rs.platformtrace.service.client.PlatformTraceDownstreamClient;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestClient;

@Configuration
@EnableConfigurationProperties(PlatformTraceClientProperties.class)
public class PlatformTraceClientConfiguration {

    @Bean
    @ConditionalOnProperty(prefix = "rs.platform-trace.clients", name = "enabled", havingValue = "true")
    public PlatformTraceDownstreamClient httpPlatformTraceDownstreamClient(
            PlatformTraceClientProperties properties
    ) {
        return new HttpPlatformTraceDownstreamClient(RestClient.builder(), properties);
    }
}
