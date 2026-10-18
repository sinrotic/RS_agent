package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.config.AgentExecutionProperties;
import com.sinrotic.rs.agent.domain.dto.AgentRuntimeSkillUpsertDTO;
import com.sinrotic.rs.agent.service.impl.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.*;

@Timeout(5)
class SkillDisableExecutionTest {
    private static final String NAME = "explicit-need-recommendation";
    private static final AgentModelStreamEvent LOAD = AgentModelStreamEvent.toolUse("load_skill", Map.of("skill_name", NAME));

    @Test
    void anOldExplicitNameCannotLoadDisabledContentAndReenableUsesCurrentContent() {
        var runtime = new InMemoryAgentRuntimeConfigurationService();
        try (var executor = new VirtualThreadAgentToolUseExecutor(runtime)) {
            assertThat(executor.execute(LOAD).join()).containsEntry("loaded", true);
            runtime.upsertSkill(NAME, new AgentRuntimeSkillUpsertDTO("private-description", "private-body", false));
            assertThat(runtime.modelContext().get("available_skills").toString()).doesNotContain(NAME);
            // 管理读取仍可看到禁用项；实际执行入口必须另行拒绝。
            assertThat(runtime.skill(NAME).enabled()).isFalse();
            assertThat(executor.execute(LOAD).join()).containsEntry("error_code", "SKILL_DISABLED")
                    .containsEntry("loaded", false).doesNotContainKeys("content", "description", "result_ref");
            runtime.upsertSkill(NAME, new AgentRuntimeSkillUpsertDTO("updated", "current-body", true));
            assertThat(executor.execute(LOAD).join()).containsEntry("status", "SUCCESS").containsEntry("content", "current-body");
        }
    }

    @Test
    void disableWhileWaitingForCapacityIsCheckedWhenTheToolActuallyRuns() throws Exception {
        var runtime = new InMemoryAgentRuntimeConfigurationService();
        var properties = new AgentExecutionProperties(); properties.setMaxToolCalls(1); properties.setToolAcquireTimeoutMs(2000);
        var limiter = new AgentExecutionLimiter(properties);
        var entered = new CountDownLatch(1); var release = new CountDownLatch(1);
        var holder = CompletableFuture.runAsync(() -> limiter.callWithToolPermit(() -> {
            entered.countDown(); release.await(); return null;
        }));
        assertThat(entered.await(1, TimeUnit.SECONDS)).isTrue();
        try (var executor = new VirtualThreadAgentToolUseExecutor(runtime,
                (VirtualThreadAgentToolUseExecutor.TriFunction<String, String, Map<String, Object>, Map<String, Object>>) (id, name, args) -> Map.of(),
                new InMemoryAgentToolResultStore(), limiter)) {
            var pending = executor.execute(LOAD);
            runtime.upsertSkill(NAME, new AgentRuntimeSkillUpsertDTO("disabled", "private-body", false));
            release.countDown();
            assertThat(pending.get(2, TimeUnit.SECONDS)).containsEntry("error_code", "SKILL_DISABLED").containsEntry("loaded", false);
        } finally { release.countDown(); holder.get(2, TimeUnit.SECONDS); }
    }
}
