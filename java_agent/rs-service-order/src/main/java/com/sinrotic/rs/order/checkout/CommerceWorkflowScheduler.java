package com.sinrotic.rs.order.checkout;
import org.springframework.context.annotation.*;
import org.springframework.scheduling.annotation.*;
import org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
@Configuration(proxyBeanMethods=false)
@EnableScheduling
@ConditionalOnProperty(name="rs.checkout.worker.enabled",havingValue="true",matchIfMissing=true)
public class CommerceWorkflowScheduler {
    private final RefundService refunds;private final TradeEventDispatcher events;
    public CommerceWorkflowScheduler(RefundService refunds,TradeEventDispatcher events) {this.refunds=refunds;this.events=events;}
    @Bean public ThreadPoolTaskScheduler commerceWorkflowScheduler() {var scheduler=new ThreadPoolTaskScheduler();scheduler.setPoolSize(3);scheduler.setThreadNamePrefix("commerce-workflow-");return scheduler;}
    @Scheduled(scheduler="commerceWorkflowScheduler",fixedDelay=1000) public void refunds() {refunds.processPending();}
    @Scheduled(scheduler="commerceWorkflowScheduler",fixedDelay=1000) public void events() {events.dispatch();}
}
