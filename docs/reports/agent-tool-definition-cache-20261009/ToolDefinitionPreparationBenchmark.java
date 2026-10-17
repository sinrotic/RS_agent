import com.sinrotic.rs.agent.service.impl.InMemoryAgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.impl.SpringAiAgentModelStreamClient;
import com.sinrotic.rs.agent.service.impl.SpringAiAgentToolCallbackFactory;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.openai.OpenAiChatOptions;
import org.springframework.ai.tool.ToolCallback;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.List;

/** 离线测量实际工具准备路径，不调用模型；不设置性能断言。 */
public class ToolDefinitionPreparationBenchmark {
    public static void main(String[] args) throws Exception {
        var runtime = new InMemoryAgentRuntimeConfigurationService();
        ChatModel model = new ChatModel() {
            public ChatResponse call(Prompt prompt) { throw new AssertionError("must not call a model"); }
        };
        var client = new SpringAiAgentModelStreamClient(model, runtime);
        var field = SpringAiAgentModelStreamClient.class.getDeclaredField("toolCallbackFactory");
        field.setAccessible(true);
        var factory = (SpringAiAgentToolCallbackFactory) field.get(client);
        Method prepare = SpringAiAgentModelStreamClient.class.getDeclaredMethod("strictToolOptions", List.class, boolean.class);
        prepare.setAccessible(true);
        for (int i = 0; i < 300; i++) run(factory, client, prepare);
        double[] samples = new double[7];
        long checksum = 0;
        for (int sample = 0; sample < samples.length; sample++) {
            long start = System.nanoTime();
            for (int i = 0; i < 1000; i++) checksum += run(factory, client, prepare);
            samples[sample] = (System.nanoTime() - start) / 1_000_000.0;
        }
        double[] ordered = samples.clone(); Arrays.sort(ordered);
        String result = "{\"scope\":\"offline actual tool preparation; excludes HTTP serialization, GPU and Agent throughput\","
            + "\"iterations_per_sample\":1000,\"samples_us_per_request\":" + Arrays.toString(samples)
            + ",\"median_us_per_request\":" + ordered[ordered.length / 2]
            + ",\"tool_count\":" + factory.createToolCallbacks().size() + ",\"checksum\":" + checksum + "}";
        Files.writeString(Path.of(args[0]), result); System.out.println(result);
    }
    private static long run(SpringAiAgentToolCallbackFactory factory, SpringAiAgentModelStreamClient client, Method prepare) throws Exception {
        List<ToolCallback> callbacks = factory.createToolCallbacks();
        var options = ((OpenAiChatOptions.Builder) prepare.invoke(client, callbacks, false)).build();
        long checksum = ((List<?>) options.getExtraBody().get("tools")).size();
        for (var callback : callbacks) checksum += callback.getToolDefinition().inputSchema().length();
        return checksum;
    }
}
