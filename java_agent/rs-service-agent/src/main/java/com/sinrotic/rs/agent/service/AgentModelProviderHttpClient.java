package com.sinrotic.rs.agent.service;

import java.util.function.Consumer;

public interface AgentModelProviderHttpClient {

    String postJson(String url, String payload, String accept);

    default void streamJson(String url, String payload, String accept, Consumer<String> lineConsumer) {
        for (String line : postJson(url, payload, accept).split("\\R")) {
            lineConsumer.accept(line);
        }
    }
}
