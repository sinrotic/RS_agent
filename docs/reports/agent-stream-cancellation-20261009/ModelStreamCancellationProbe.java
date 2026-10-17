import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.config.AgentModelProviderConfiguration;
import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.service.AgentModelStreamClient;
import com.sinrotic.rs.agent.service.impl.SpringAiAgentModelStreamClient;
import com.sinrotic.rs.agent.service.impl.OpenAiModelStreamResources;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.ChatOptions;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.openai.OpenAiChatOptions;
import reactor.core.publisher.Flux;
import org.springframework.ai.model.chat.client.autoconfigure.ChatClientAutoConfiguration;
import org.springframework.ai.model.openai.autoconfigure.OpenAiChatAutoConfiguration;
import org.springframework.ai.model.tool.autoconfigure.ToolCallingAutoConfiguration;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/** 仅测真实模型流停止后的残留请求；不测回答质量或最大 Agent 并发，不修改模型部署。 */
public class ModelStreamCancellationProbe {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final HttpClient HTTP = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(3)).build();
    private static final class Stop extends RuntimeException {}

    public static void main(String[] args) throws Exception {
        String endpoint = args[0];
        Path output = Path.of(args[1]);
        List<Map<String, Object>> samples = new ArrayList<>();
        new ApplicationContextRunner()
                .withConfiguration(AutoConfigurations.of(ToolCallingAutoConfiguration.class,
                        OpenAiChatAutoConfiguration.class, ChatClientAutoConfiguration.class))
                .withUserConfiguration(AgentModelProviderConfiguration.class)
                .withPropertyValues("rs.agent.model-provider.type=spring_ai", "spring.ai.model.chat=openai",
                        "spring.ai.chat.client.tool-calling.enabled=false", "spring.ai.openai.base-url=" + endpoint + "/v1",
                        "spring.ai.openai.api-key=local-unused", "spring.ai.openai.chat.options.model=qwen35-4b",
                        "spring.ai.openai.chat.options.temperature=0", "spring.ai.openai.chat.options.max-tokens=1536")
                .run(context -> {
                    ChatModel base = context.getBean(ChatModel.class);
                    AtomicBoolean scopePresent = new AtomicBoolean();
                    ChatModel model = new ChatModel() {
                        public ChatResponse call(Prompt prompt) { throw new AssertionError("must use streaming"); }
                        public ChatOptions getOptions() { return base.getOptions(); }
                        public Flux<ChatResponse> stream(Prompt prompt) {
                            if (!(prompt.getOptions() instanceof OpenAiChatOptions original)) {
                                throw new IllegalStateException("探针丢失模型专用 options：" + prompt.getOptions().getClass().getName());
                            }
                            scopePresent.set(original.getCustomHeaders() != null && original.getCustomHeaders().containsKey("X-RS-Agent-Stream-Scope"));
                            // 仅为探针统一关闭 thinking，两个组使用完全相同的参数。
                            var options = original.mutate().extraBody(Map.of("chat_template_kwargs", Map.of("enable_thinking", false))).build();
                            return base.stream(new Prompt(prompt.getInstructions(), options));
                        }
                    };
                    var control = new SpringAiAgentModelStreamClient(model);
                    var optimized = new SpringAiAgentModelStreamClient(model, null, null, false,
                            context.getBean(OpenAiModelStreamResources.class));
                    try {
                        for (int repeat = 0; repeat < 2; repeat++) {
                            samples.add(sample(endpoint, "java_stream_close_only", repeat, control, scopePresent));
                            save(output, samples);
                            samples.add(sample(endpoint, "http_cancellation", repeat, optimized, scopePresent));
                            save(output, samples);
                        }
                    } catch (Exception error) {
                        throw new IllegalStateException(error);
                    }
                });
        System.out.println(JSON.writeValueAsString(samples));
        // 探针结束后退出本进程，避免 SDK 的空闲 HTTP 线程延长命令等待。
        System.exit(0);
    }

    private static Map<String, Object> sample(String endpoint, String label, int repeat, AgentModelStreamClient client, AtomicBoolean scopePresent) throws Exception {
        var idle = metrics(endpoint);
        if (idle.get("running") != 0 || idle.get("waiting") != 0) {
            throw new IllegalStateException("模型不是空闲状态，不与其他请求混测");
        }
        CountDownLatch firstToken = new CountDownLatch(1);
        CountDownLatch stop = new CountDownLatch(1);
        var executor = Executors.newVirtualThreadPerTaskExecutor();
        try {
            var result = executor.submit(() -> {
                try {
                    client.streamAssistantEvents("cancel-" + label + repeat,
                            new AgentChatRequestDTO("cancel-probe", "cancel-probe", "从1到200逐项解释不同的生活科学常识，每项不少于30字。持续写到200项，不要提前总结结束。", 1,
                                    Map.of("system_prompt", "这是纯文本压力测试，请直接持续回答，不调用工具。")), event -> {
                                if (event.isToken()) {
                                    firstToken.countDown();
                                    try {
                                        if (!stop.await(5, TimeUnit.SECONDS)) throw new IllegalStateException("停止信号超时");
                                    } catch (InterruptedException error) {
                                        Thread.currentThread().interrupt();
                                        throw new IllegalStateException(error);
                                    }
                                    throw new Stop();
                                }
                            });
                    throw new IllegalStateException("未提前停止模型流");
                } catch (Stop expected) {
                    return null;
                }
            });
            if (!firstToken.await(15, TimeUnit.SECONDS)) throw new IllegalStateException("模型未返回首个 token");
            if (scopePresent.get() != label.equals("http_cancellation")) {
                throw new IllegalStateException("探针配置与实际 transport scope 不一致");
            }
            Map<String, Double> beforeStop = metrics(endpoint);
            long observeDeadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(3);
            while (beforeStop.get("running") < 1 && System.nanoTime() < observeDeadline) {
                Thread.sleep(100);
                beforeStop = metrics(endpoint);
            }
            long stopTime = System.nanoTime();
            stop.countDown();
            result.get(3, TimeUnit.SECONDS);
            double appExitMs = (System.nanoTime() - stopTime) / 1_000_000.0;
            List<Map<String, Object>> observed = new ArrayList<>();
            long drainDeadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(35);
            Map<String, Double> current;
            do {
                current = metrics(endpoint);
                observed.add(Map.of("ms_after_stop", (System.nanoTime() - stopTime) / 1_000_000.0, "metrics", current));
                if (current.get("running") == 0 && current.get("waiting") == 0) break;
                Thread.sleep(100);
            } while (System.nanoTime() < drainDeadline);
            if (current.get("running") != 0 || current.get("waiting") != 0) throw new IllegalStateException("模型请求未清空");
            var sample = new LinkedHashMap<String, Object>();
            sample.put("configuration", label);
            sample.put("repeat", repeat);
            sample.put("transport_scope_present", scopePresent.get());
            sample.put("before_stop", beforeStop);
            sample.put("app_exit_ms", appExitMs);
            sample.put("metrics_idle_observed_ms", (System.nanoTime() - stopTime) / 1_000_000.0);
            sample.put("generated_tokens_after_stop", current.get("generated_tokens") - beforeStop.get("generated_tokens"));
            sample.put("observations", observed);
            return sample;
        } finally {
            stop.countDown();
            executor.shutdownNow();
        }
    }

    private static Map<String, Double> metrics(String endpoint) throws Exception {
        var response = HTTP.send(HttpRequest.newBuilder(URI.create(endpoint + "/metrics")).timeout(Duration.ofSeconds(5)).GET().build(), HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() != 200) throw new IllegalStateException("metrics HTTP " + response.statusCode());
        var values = new LinkedHashMap<String, Double>(Map.of("running", 0.0, "waiting", 0.0, "generated_tokens", 0.0));
        for (String line : response.body().split("\n")) {
            if (line.startsWith("vllm:num_requests_running{") || line.startsWith("vllm:num_requests_waiting{") || line.startsWith("vllm:generation_tokens_total{")) {
                String key = line.startsWith("vllm:num_requests_running{") ? "running" : line.startsWith("vllm:num_requests_waiting{") ? "waiting" : "generated_tokens";
                values.put(key, values.get(key) + Double.parseDouble(line.substring(line.lastIndexOf(' ') + 1)));
            }
        }
        return values;
    }

    private static void save(Path output, List<Map<String, Object>> samples) throws Exception {
        Files.writeString(output, JSON.writerWithDefaultPrettyPrinter().writeValueAsString(Map.of(
                "scope", "GPU 1 BF16 原部署；纯文本停止探针，输出预算1536；不代表最大 Agent 并发或功能质量。",
                "control", "对照仅关闭 Java Stream；优化组使用同一 ChatModel，并传递实际 HTTP 取消。",
                "measurement_limit", "running 和 token 计数受服务端指标刷新间隔影响，观察到空闲的时间不等于精确取消延迟。",
                "samples", samples)) + "\n");
    }
}
