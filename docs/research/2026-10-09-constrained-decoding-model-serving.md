# 约束解码与模型服务接入调研

调研日期：2026-10-09。范围：官方文档、原始论文及当前工作区代码。本文是接入建议，未修改服务实现，未启动模型，也未验证远程部署的实际版本。

## 结论

结合仓库现有设计，建议优先采用 **vLLM + XGrammar**。`rs-service-model` 接收结构化输出要求、选择支持该能力的模型并转换调用协议；逐 token 的约束由推理 runtime 执行。先补真实 chat 转发，再实现 JSON Schema 输出和严格工具参数。这个选择来自项目已经规划 vLLM 的服务边界，而不是声称它在所有负载下都最快。

vLLM 当前官方文档支持 XGrammar、guidance 后端；SGLang 也支持约束生成，默认后端为 XGrammar。两者都能通过兼容接口接收结构化输出要求。[vLLM 结构化输出](https://docs.vllm.ai/en/stable/features/structured_outputs/)、[SGLang 结构化输出](https://docs.sglang.io/docs/advanced_features/structured_outputs)

## 原理与能力边界

通常的自回归生成从词表中采样下一个 token。约束解码依据已经生成的前缀和目标语法计算允许集合，把不合法 token 的概率屏蔽，再从合法集合中采样。约束状态随输出更新，并且必须适配 tokenizer：一个 token 可能覆盖多个字符和语法边界。XGrammar 是实现这类约束生成的引擎。[XGrammar 原始论文](https://arxiv.org/abs/2411.15100)

常见约束包括：JSON Schema 指定结构与字段类型、枚举限定分类标签、regex 限定简单格式、grammar 指定更一般的语言。vLLM 文档分别提供 `json`、`choice`、`regex`、`grammar` 和 `structural_tag` 接口。[vLLM 接口说明](https://docs.vllm.ai/en/stable/features/structured_outputs/)

这与三个相邻概念需要区分：

| 做法 | 控制位置 | 工程含义 |
| --- | --- | --- |
| 提示模型按格式输出 | 输入提示 | 能引导模型，但不能提供解码期强制约束 |
| 返回后解析、校验和重试 | 生成完成之后 | 能发现坏结果，并可能修复；不是逐 token 约束 |
| 约束解码 | 推理生成过程 | 控制允许输出的形式，但仍需完整输出与业务校验 |

上表是依据约束解码机制作出的工程区分。网关只有 HTTP 输出、无法访问生成过程时，不能在网关自行实现等价的 token 约束；外部供应商必须提供对应能力。

语法合规不代表事实正确。把商品 ID 写进支持的 `enum` 可以限制输出范围，但商品是否满足需求、价格是否最新、工具选择是否合理仍由业务判断。流式中间片段也只是合法前缀；截断、超时和取消都可能让最终对象不完整。不能把“前缀受约束”当成“请求一定成功完成”。这些是机制边界与接入要求，不是对线上效果的实测结论。

## 技术选择

| 方案 | 适用位置 | 本仓库建议 |
| --- | --- | --- |
| vLLM + XGrammar | 独立 LLM 推理 runtime | 首选，沿用既有模型服务设计 |
| SGLang + XGrammar | 独立 LLM 推理 runtime | 若后续选择 SGLang，也可保留网关的业务契约 |
| Outlines | 结构化生成库与不同模型后端适配 | 自管 Python 生成链路时可评估；先明确具体后端如何执行约束 |
| LM Format Enforcer | JSON Schema / regex 格式约束库 | 自管 Python 推理时可评估；不作为当前 Java 网关第一步 |

能力资料：[vLLM](https://docs.vllm.ai/en/stable/features/structured_outputs/)、[SGLang](https://docs.sglang.io/docs/advanced_features/structured_outputs)、[Outlines 模型适配](https://dottxt-ai.github.io/outlines/1.0.2/features/models/)、[LM Format Enforcer 官方仓库](https://github.com/noamgat/lm-format-enforcer)。这些是不同层次的方案；表中的优先级是针对本仓库的判断。

## vLLM 参数与版本注意点

普通结构化内容优先使用 `response_format.type=json_schema`；枚举、regex、grammar 等扩展使用 `structured_outputs`。官方文档说明旧 `guided_json`、`guided_regex`、`guided_choice`、`guided_grammar` 等字段已在 v0.12.0 移除，不能直接照抄旧教程。[vLLM 参数迁移](https://docs.vllm.ai/en/stable/features/structured_outputs/)

一个普通 JSON 输出请求的形状如下，仅用于解释 runtime 协议，未实际执行：

```json
{
  "model": "agent_4b",
  "messages": [
    {"role": "user", "content": "识别购物意图，按指定字段返回 JSON。"}
  ],
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "shopping_intent",
      "schema": {
        "type": "object",
        "properties": {
          "intent": {"type": "string", "enum": ["recommend", "compare", "clarify"]},
          "query": {"type": "string"}
        },
        "required": ["intent", "query"],
        "additionalProperties": false
      }
    }
  }
}
```

这是基于官方示例改写的应用示例；`model` 必须换成 runtime 实际注册的模型名称。[官方 JSON Schema 示例](https://docs.vllm.ai/en/stable/features/structured_outputs/)

后端选择属于服务端配置，当前文档使用 `--structured-outputs-config.backend`，默认 `auto`。需要可复现的接入验证时，可在已确认支持的版本固定为 `xgrammar`。[vLLM 后端配置](https://docs.vllm.ai/en/stable/features/structured_outputs/)

## 工具调用约束需要单独接入

现有 Agent 把工具调用作为主要输出协议，因此优先约束 `tools[].function.parameters`，特别是 `emit_final_answer`。不要把普通 `response_format` 当成完整的工具调用接入。

当前 vLLM stable/latest 文档都区分：是否必须调用工具、是否约束工具调用外层格式、是否严格约束每个工具的参数。对于 structural-tag 路径，`required` 和指定工具会激活外层约束，但参数约束仍取决于该工具的 `strict: true` 或服务端 `--tool-strict-level parameter`；schema-derived JSON 路径的 named/required 仍按工具参数 schema 约束。`auto` 也可约束，但需满足文档列出的 strict 配置与 parser 支持条件。[vLLM 工具调用与 Strict Mode](https://docs.vllm.ai/en/stable/features/tool_calling/)、[latest 文档](https://docs.vllm.ai/en/latest/features/tool_calling/)

因此不能泛化为“auto 一定没有约束”，也不能泛化为“required 一定严格约束每个参数”。上线前必须确认实际 vLLM 镜像版本、模型、chat template、tool parser 和参数组合；文档中的新选项不表示任何旧部署都支持。

严格工具 schema 的兼容写法包括：每层对象 `additionalProperties: false`，属性全部放入 `required`，可选值允许 `null`。工具解析器、推理模型的 reasoning 配置和并行调用支持也需要逐组合验证。[严格工具 schema 建议与 parser 说明](https://docs.vllm.ai/en/stable/features/tool_calling/)、[结构化输出与 reasoning](https://docs.vllm.ai/en/stable/features/structured_outputs/)

## 当前仓库的接入事实

以下来自调研时工作区，包括已有未提交文件；不能据此推断远程已部署相同实现。

1. `java_agent/rs-service-model/MODEL_SERVING_DESIGN.md` 规划的是模型网关转发到 vLLM，网关负责注册、路由和调用协议，不自行实现推理引擎。
2. 当前生产 `HttpModelGatewayService` 仅实现 embedding/rerank 转发；`chat` 与 `streamChat` 直接返回 capability 未配置的 503。`ConfiguredModelRegistryService` 也仅登记这两个运行时能力。
3. `ModelChatRequestDTO` 当前只有 `model_key`、`request_id`、`messages`、`options`，没有明确的输出约束和工具调用契约。
4. `ModelGatewayService.streamChat` 返回 `List<ModelChatStreamEventVO>`，`InternalModelChatController` 在取得列表后写出 SSE；这个接口形状不是实时消费上游流。
5. `ModelChatStreamEventVO` 只有 `event/request_id/delta/done`，没有工具调用 ID、工具名或参数分片字段。
6. `SelfHostedModelStreamClient` 发出单个 user message、`context` 和 `options.stream`，而模型 chat DTO 没有接收 `context`；该客户端期望的 `tool_use/name/arguments` 也没有完整的模型服务输出契约支持。
7. Agent 另有 `python_api/self_hosted/spring_ai` 通道；`SpringAiAgentModelStreamClient` 已绑定真实 tool callbacks。`application.yml` 配置了 `tool-choice: required` 与 `parallel-tool-calls: true`，但这不证明外部供应商实际执行了严格参数约束。
8. `InMemoryAgentRuntimeConfigurationService.finalAnswerToolSchema` 已采用禁止额外属性、所有字段 required、部分值允许 null 的形状；其他工具需逐个检查。

依据文件：

- `java_agent/rs-service-model/src/main/java/com/sinrotic/rs/model/service/impl/HttpModelGatewayService.java`
- `java_agent/rs-service-model/src/main/java/com/sinrotic/rs/model/service/impl/ConfiguredModelRegistryService.java`
- `java_agent/rs-service-model/src/main/java/com/sinrotic/rs/model/domain/dto/ModelChatRequestDTO.java`
- `java_agent/rs-service-model/src/main/java/com/sinrotic/rs/model/service/ModelGatewayService.java`
- `java_agent/rs-service-model/src/main/java/com/sinrotic/rs/model/controller/internal/InternalModelChatController.java`
- `java_agent/rs-service-model/src/main/java/com/sinrotic/rs/model/domain/vo/ModelChatStreamEventVO.java`
- `java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/SelfHostedModelStreamClient.java`
- `java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/SpringAiAgentModelStreamClient.java`
- `java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/InMemoryAgentRuntimeConfigurationService.java`
- `java_agent/rs-service-agent/src/main/resources/application.yml`

## 建议的最小实施顺序

下述内容是设计建议，不是已经实现的功能：

1. 确认目标模型和 runtime 版本，登记 chat endpoint 与结构化输出能力；补 `rs-service-model` 的真实 LLM chat 转发。
2. 定义普通文本、JSON Schema、严格工具调用的明确请求契约。业务传 schema/工具定义，网关适配 runtime 字段；不支持的约束明确失败，不能静默改成无约束生成。
3. 先验证非流式 JSON Schema 请求，再支持实时上游 SSE、取消、超时、结束原因和错误映射。
4. 补完整工具协议，包括历史消息中的工具结果、tool call ID、参数分片重组；完整参数形成并校验后才交给 Agent 执行。
5. 接入现有 `emit_final_answer`，再扩展到其他工具。首轮评估可在支持的模型/parser上关闭并行工具调用，减少协议组合；后续按实测逐项开启。
6. 保留公开输出投影与业务校验。ADR-0012 要求 `PublicAgentResponseProjector` 校验输出类型、Profile allowlist 和字段边界，约束解码不能替代这个入口。

服务边界应保持：

```text
rs-service-agent：选择本轮工具与输出要求，执行完整且已校验的工具调用
        ↓
rs-service-model：能力检查、模型路由、协议适配、真实流转发
        ↓
vLLM + XGrammar：在 token 生成过程中执行约束
```

## 验证与性能观察

建议用同一模型、同一输入，对比无约束/受约束请求。至少观察：完整输出 JSON/Schema 合规率、工具参数合规率、业务内容正确率、输出截断率、首 token 延迟、总延迟和并发吞吐。把冷 schema 的首次编译与热 schema 的重复请求分开测量；复杂 schema 和每次变化的候选 ID 枚举可能改变编译与缓存收益，需要实际测量，不能直接把论文中的加速数字写成本服务收益。

应覆盖中文、引号和转义、null、枚举、数组边界、超长生成、取消、上游错误、不支持的 schema、工具参数跨分片等情况。JSON Schema 的合法关键词不等于选定后端会支持并强制执行所有关键词，必须以固定版本的能力测试验收。

这里没有给出实测性能数字。按照 `CLAUDE.md`，本机任务默认按 12GB 可承受、14GB 上限控制；真实模型与并发验证优先在现有远程推理资源上进行。

## 尚需确认的信息

- 实际准备接入的模型名称及推理框架、镜像版本；设计文档中的 Agent 4B/vLLM 不能代替部署事实。
- 是否计划把现有 `spring_ai` 外部调用统一迁移到模型服务，还是先为 `self_hosted` 增加能力。
- 先做普通结构化输出、严格工具参数，还是二者都需要；是否开启 reasoning 和并行工具调用。

这些信息影响实施配置与验收范围，不影响上述机制说明和当前代码缺口判断。
