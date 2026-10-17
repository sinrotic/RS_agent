package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.domain.vo.AgentTraceEventVO;
import com.sinrotic.rs.agent.service.AgentTraceReporter;
import java.util.List;

/** 每个目标有独立队列及失败统计；单个目标故障不阻断其他目标。 */
public final class CompositeAgentTraceReporter implements AgentTraceReporter {
    private final List<AgentTraceReporter> reporters;
    public CompositeAgentTraceReporter(List<AgentTraceReporter> reporters) { this.reporters = List.copyOf(reporters); }
    @Override public void report(AgentTraceEventVO event) {
        for (var reporter : reporters) try { reporter.report(event); }
        catch (RuntimeException ignored) { System.getLogger(getClass().getName()).log(System.Logger.Level.WARNING, "Trace target failed"); }
    }
    @Override public void close() {
        for (var reporter : reporters) try { reporter.close(); }
        catch (RuntimeException ignored) { System.getLogger(getClass().getName()).log(System.Logger.Level.WARNING, "Trace target close failed"); }
    }
}
