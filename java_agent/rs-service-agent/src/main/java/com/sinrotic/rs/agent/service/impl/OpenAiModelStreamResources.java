package com.sinrotic.rs.agent.service.impl;

import okhttp3.Call;
import okhttp3.Interceptor;
import okhttp3.Response;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/** 将单次模型流的生命周期连接到实际 HTTP 调用，不依赖工作线程亲和。 */
public final class OpenAiModelStreamResources implements Interceptor {

    private static final String SCOPE_HEADER = "X-RS-Agent-Stream-Scope";

    private final Map<String, Scope> scopes = new ConcurrentHashMap<>();

    public Scope open() {
        var scope = new Scope(UUID.randomUUID().toString());
        scopes.put(scope.token, scope);
        return scope;
    }

    @Override
    public Response intercept(Chain chain) throws IOException {
        String token = chain.request().header(SCOPE_HEADER);
        if (token == null) {
            return chain.proceed(chain.request());
        }
        Scope scope = scopes.get(token);
        if (scope == null || !scope.attach(chain.call())) {
            chain.call().cancel();
            throw new IOException("agent model stream already closed");
        }
        // 此标识只用于进程内关联，不发送给模型服务。
        return chain.proceed(chain.request().newBuilder().removeHeader(SCOPE_HEADER).build());
    }

    public final class Scope implements AutoCloseable {
        private final String token;
        private final List<Call> calls = new ArrayList<>();
        private boolean closed;

        private Scope(String token) {
            this.token = token;
        }

        public Map<String, String> headers() {
            return Map.of(SCOPE_HEADER, token);
        }

        private synchronized boolean attach(Call call) {
            if (closed) {
                return false;
            }
            calls.add(call);
            return true;
        }

        @Override
        public void close() {
            List<Call> activeCalls;
            synchronized (this) {
                if (closed) {
                    return;
                }
                closed = true;
                activeCalls = List.copyOf(calls);
                calls.clear();
            }
            scopes.remove(token, this);
            activeCalls.forEach(Call::cancel);
        }
    }
}
