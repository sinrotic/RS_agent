package com.sinrotic.rs.agent.service;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.ResponseStatus;

@ResponseStatus(HttpStatus.NOT_FOUND)
public class AgentSessionNotFoundException extends RuntimeException {

    public AgentSessionNotFoundException() {
        super("Agent session was not found");
    }
}
