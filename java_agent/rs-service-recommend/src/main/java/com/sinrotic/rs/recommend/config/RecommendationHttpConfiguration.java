package com.sinrotic.rs.recommend.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.web.client.RestClient;
import java.time.Duration;

@Configuration
public class RecommendationHttpConfiguration {
    private final java.net.http.HttpClient httpClient = java.net.http.HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(2)).build();
    @Bean
    @org.springframework.context.annotation.Scope("prototype")
    public RestClient.Builder recommendationRestClientBuilder() {
        var factory = new JdkClientHttpRequestFactory(httpClient);
        factory.setReadTimeout(Duration.ofSeconds(20));
        return RestClient.builder().requestFactory(factory);
    }
}
