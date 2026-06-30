package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.domain.session.AgentToolResultLines;

import java.util.List;

public interface AgentToolResultStore {

    void saveLines(String resultRef, List<String> lines);

    AgentToolResultLines readLines(String resultRef, int offset, int limit);
}
