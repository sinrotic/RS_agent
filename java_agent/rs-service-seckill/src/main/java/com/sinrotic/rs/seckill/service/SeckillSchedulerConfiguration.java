package com.sinrotic.rs.seckill.service;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler;

@Configuration(proxyBeanMethods=false)
public class SeckillSchedulerConfiguration {
    @Bean
    public ThreadPoolTaskScheduler seckillScheduler() {
        var scheduler=new ThreadPoolTaskScheduler();
        scheduler.setPoolSize(3);
        scheduler.setThreadNamePrefix("seckill-scheduler-");
        scheduler.setRemoveOnCancelPolicy(true);
        return scheduler;
    }
}
