package com.sinrotic.rs.seckill.service;

import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import org.apache.kafka.clients.admin.AdminClient;
import org.apache.kafka.clients.admin.OffsetSpec;
import org.apache.kafka.common.TopicPartition;
import org.springframework.kafka.core.KafkaAdmin;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler;
import java.util.*;
import java.util.concurrent.TimeUnit;

@Configuration(proxyBeanMethods=false)
@EnableScheduling
@ConditionalOnProperty(name="rs.commerce.kafka-monitor.enabled",havingValue="true",matchIfMissing=true)
public class CommerceKafkaMetrics {
    private final AdminClient admin;
    private volatile double lag=Double.NaN,deadLetters=Double.NaN,success=0;
    public CommerceKafkaMetrics(KafkaAdmin kafkaAdmin,MeterRegistry registry) {
        admin=AdminClient.create(kafkaAdmin.getConfigurationProperties());
        Gauge.builder("rs_commerce_kafka_consumer_lag",this,probe->probe.lag).register(registry);
        Gauge.builder("rs_commerce_kafka_dead_letter_records",this,probe->probe.deadLetters).register(registry);
        Gauge.builder("rs_commerce_kafka_probe_success",this,probe->probe.success).register(registry);
    }
    @Bean public ThreadPoolTaskScheduler seckillMonitoringScheduler() {
        var scheduler=new ThreadPoolTaskScheduler();scheduler.setPoolSize(1);scheduler.setThreadNamePrefix("commerce-kafka-monitor-");return scheduler;
    }
    @Scheduled(scheduler="seckillMonitoringScheduler",initialDelay=10000,fixedDelay=30000)
    public void refresh() {
        try {
            var topics=admin.describeTopics(List.of("checkout-seckill-accepted","checkout-seckill-accepted.DLT")).allTopicNames().get(2,TimeUnit.SECONDS);
            var latest=new HashMap<TopicPartition,OffsetSpec>();
            for(var topic:topics.values()) for(var partition:topic.partitions()) latest.put(new TopicPartition(topic.name(),partition.partition()),OffsetSpec.latest());
            var ends=admin.listOffsets(latest).all().get(2,TimeUnit.SECONDS);
            var committed=admin.listConsumerGroupOffsets("rs-checkout-seckill-v1").partitionsToOffsetAndMetadata().get(2,TimeUnit.SECONDS);
            long pending=0,dead=0;
            for(var entry:ends.entrySet()) {
                if(entry.getKey().topic().endsWith(".DLT")) dead+=entry.getValue().offset();
                else {
                    var position=committed.get(entry.getKey());
                    pending+=Math.max(0,entry.getValue().offset()-(position==null ? 0 : position.offset()));
                }
            }
            lag=pending;deadLetters=dead;success=1;
        } catch(Exception unavailable) {
            if(unavailable instanceof InterruptedException) Thread.currentThread().interrupt();
            lag=Double.NaN;deadLetters=Double.NaN;success=0;
        }
    }
    @jakarta.annotation.PreDestroy public void close() {admin.close(java.time.Duration.ofSeconds(1));}
}
