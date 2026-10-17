package com.sinrotic.rs.agent.service;

import java.math.BigDecimal;

/** Internal recommendation evidence; never projected directly onto the public response. */
public record AgentRecommendationFact(BigDecimal price) { }
