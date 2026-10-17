package com.sinrotic.rs.order.config;

import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.env.Environment;
import org.springframework.kafka.annotation.EnableKafka;
import org.springframework.kafka.config.ConcurrentKafkaListenerContainerFactory;
import org.springframework.kafka.core.DefaultKafkaConsumerFactory;
import org.springframework.kafka.core.ConsumerFactory;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.common.serialization.StringDeserializer;
import tools.jackson.databind.json.JsonMapper;

import java.util.HashMap;
import java.util.Map;

@Configuration(proxyBeanMethods = false)
@EnableKafka
public class OrderKafkaConfiguration {

    @Bean
    @ConditionalOnMissingBean
    public ConsumerFactory<Object, Object> kafkaConsumerFactory(Environment environment) {
        Map<String, Object> properties = new HashMap<>();
        properties.put(
                ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG,
                environment.getProperty("spring.kafka.bootstrap-servers", "localhost:9092")
        );
        properties.put(ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class);
        properties.put(ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class);
        properties.put(ConsumerConfig.ENABLE_AUTO_COMMIT_CONFIG, false);
        properties.put(
                ConsumerConfig.AUTO_OFFSET_RESET_CONFIG,
                environment.getProperty("spring.kafka.consumer.auto-offset-reset", "latest")
        );
        return new DefaultKafkaConsumerFactory<>(properties);
    }

    @Bean(name = "kafkaListenerContainerFactory")
    @ConditionalOnMissingBean(name = "kafkaListenerContainerFactory")
    public ConcurrentKafkaListenerContainerFactory<Object, Object> kafkaListenerContainerFactory(
            ConsumerFactory<Object, Object> consumerFactory,
            Environment environment,
            org.springframework.beans.factory.ObjectProvider<org.springframework.kafka.core.KafkaTemplate<Object,Object>> templates
    ) {
        ConcurrentKafkaListenerContainerFactory<Object, Object> factory =
                new ConcurrentKafkaListenerContainerFactory<>();
        factory.setConsumerFactory(consumerFactory);
        factory.setConcurrency(environment.getProperty("rs.checkout.kafka.concurrency",Integer.class,3));
        var template = templates.getIfAvailable();
        if (template != null) {
            var recoverer = new org.springframework.kafka.listener.DeadLetterPublishingRecoverer(template);
            recoverer.setFailIfSendResultIsError(true);
            factory.setCommonErrorHandler(new org.springframework.kafka.listener.DefaultErrorHandler(
                    recoverer,new org.springframework.util.backoff.FixedBackOff(1000L,5L)));
        }
        factory.setAutoStartup(environment.getProperty("spring.kafka.listener.auto-startup", Boolean.class, true));
        return factory;
    }

    @Bean
    @ConditionalOnMissingBean
    public JsonMapper jsonMapper() {
        return new JsonMapper();
    }
}
