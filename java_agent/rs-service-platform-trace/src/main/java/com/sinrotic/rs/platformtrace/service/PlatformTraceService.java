package com.sinrotic.rs.platformtrace.service;

import com.sinrotic.rs.platformtrace.domain.vo.AgentSessionTraceVO;
import com.sinrotic.rs.platformtrace.domain.vo.AgentTraceEventVO;
import com.sinrotic.rs.platformtrace.domain.vo.AgentTraceEventsVO;
import com.sinrotic.rs.platformtrace.domain.vo.PlatformAccountProfileVO;
import com.sinrotic.rs.platformtrace.domain.vo.PlatformInteractionEventVO;
import com.sinrotic.rs.platformtrace.domain.vo.PlatformSessionOverviewVO;
import com.sinrotic.rs.platformtrace.domain.vo.PlatformTimelineEventVO;
import com.sinrotic.rs.platformtrace.domain.vo.RecommendTraceVO;

import java.util.List;

public interface PlatformTraceService {

    PlatformAccountProfileVO accountProfile(String accountId);

    RecommendTraceVO recommendTrace(String requestId);

    AgentSessionTraceVO agentSessionTurns(String sessionId);

    AgentTraceEventsVO agentRequestEvents(String requestId);

    List<PlatformInteractionEventVO> interactionEvents(String sessionId);

    List<PlatformTimelineEventVO> sessionTimeline(String sessionId);

    PlatformSessionOverviewVO sessionOverview(String sessionId, String accountId, String requestId);

    void saveAccountProfile(PlatformAccountProfileVO profile);

    void saveRecommendTrace(RecommendTraceVO trace);

    void saveAgentSessionTrace(AgentSessionTraceVO trace);

    AgentTraceEventVO saveAgentTraceEvent(AgentTraceEventVO event);

    PlatformInteractionEventVO saveInteractionEvent(PlatformInteractionEventVO event);
}
