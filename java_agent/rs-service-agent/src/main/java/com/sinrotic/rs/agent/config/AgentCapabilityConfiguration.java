package com.sinrotic.rs.agent.config;

import com.sinrotic.rs.agent.service.AgentCapabilityRegistry;
import com.sinrotic.rs.agent.service.AgentCapabilityAuditSink;
import com.sinrotic.rs.agent.service.AgentDelegateService;
import com.sinrotic.rs.agent.service.AgentHotSessionStore;
import com.sinrotic.rs.agent.service.AgentRecommendationService;
import com.sinrotic.rs.agent.service.AgentTraceReporter;
import com.sinrotic.rs.agent.service.impl.AgentRecommendationCapability;
import com.sinrotic.rs.agent.service.impl.AgentRagExplainCapability;
import com.sinrotic.rs.agent.service.impl.AgentSessionMemoryCapability;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentCapabilityRegistry;
import com.sinrotic.rs.agent.service.impl.TraceReportingAgentCapabilityAuditSink;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration(proxyBeanMethods = false)
public class AgentCapabilityConfiguration {

    @Bean
    @ConditionalOnMissingBean(AgentCapabilityRegistry.class)
    public AgentCapabilityRegistry agentCapabilityRegistry(
            ObjectProvider<AgentDelegateService> delegateServiceProvider,
            ObjectProvider<AgentHotSessionStore> hotSessionStoreProvider,
            ObjectProvider<AgentRecommendationService> recommendationServiceProvider,
            ObjectProvider<AgentTraceReporter> traceReporterProvider
    ) {
        AgentTraceReporter traceReporter = traceReporterProvider.getIfAvailable();
        AgentCapabilityAuditSink auditSink = traceReporter == null
                ? event -> {
                }
                : new TraceReportingAgentCapabilityAuditSink(traceReporter);
        InMemoryAgentCapabilityRegistry registry = new InMemoryAgentCapabilityRegistry(
                auditSink
        );
        delegateServiceProvider.ifAvailable(delegateService -> registry.register(new AgentRagExplainCapability(delegateService)));
        hotSessionStoreProvider.ifAvailable(store -> registry.register(new AgentSessionMemoryCapability(store)));
        recommendationServiceProvider.ifAvailable(service -> registry.register(new AgentRecommendationCapability(service)));
        return registry;
    }
}
