# Agent 并发优化研究与实施顺序

研究日期：2026-10-09。依据本仓库源码、[已完成的压测](README.md)和官方资料；本次只研究并记录方案，没有修改模型服务或业务配置，没有执行新的性能测试。

## 判断依据

目标应是：在回答质量、工具链健康率和延迟门槛不降低的条件下，提高每秒完成的 Turn 数。单独增加排队中的 Turn 数，不能证明服务能力提高。

- 默认 `maxModelStreams=8`、等待 200ms 造成第 9 路开始快速拒绝。提高额度可以解除应用侧限制，但不等于提高 GPU 吞吐。
- 104 并发为 3.633 Turn/s、P95 28.157 秒；192 并发为 3.839 Turn/s、P95 49.006 秒。单卡吞吐已出现平台趋势，仍需区分模型计算、输入处理、缓存和排队的具体贡献。
- 104 档产生 528 次模型调用，平均 **1.692 次/Turn**；累计输入 2,783,961 token，平均约 **5273 token/模型调用**。这些是该档模型指标增量，包含工具调用产生的后续生成，不是单独测量的系统提示词大小。
- 同档 prefix cache 指标增量：queries=5,198,843、hits=3,726,624，计数命中比例 **71.68%**。混合架构的内部查询计数不等同于 API 输入 token 数；不能把这一比例解释为消除了同等比例的耗时。
- 比较样本全部遭遇不可用 RAG 工具，随后继续生成，平均约 5 次模型调用。应优先解决工具可用性和失败后的继续调用，再评价正常比较业务的吞吐。
- 有效数据基于临时 16K 上下文、2GiB Java 堆、内存 Session 和固定候选；原 4K 配置单请求失败，512MiB 正式容器和真实依赖链路未覆盖。

上述数字来自 [boundary-exclusive.json](boundary-exclusive.json)、[raised-sweep.json](raised-sweep.json) 与 [工具审计](comparison-tool-audit.json)。

## 第一优先级：减少模型必须完成的工作

### 1. 为简单 Turn 提供一次模型调用的路径

本项目主要调用注册的端口服务，业务阶段相对明确。建议按会话状态和意图划分路径：

| 场景 | 建议编排 | 验证点 |
|---|---|---|
| 需求不完整、仅需追问 | 精简上下文，只允许最终回答；需要时由服务端注入短澄清规则 | 是否一次调用即可提出正确问题 |
| 普通知识建议、明确不检索 | 不暴露推荐/RAG 工具，只保留最终回答所需 schema | 不虚构商品事实、不触发无关检索 |
| 条件完整的商品推荐 | 已知条件直接调用既有推荐服务，再让模型组织回答 | 真实候选和证据正确进入回答 |
| 复杂比较或多步探索 | 保留 Agent Loop，按阶段提供工具 | 复杂能力和证据质量不退化 |

这是本项目的设计建议。官方经验支持对明确任务使用可预测工作流，并通过路由区分任务，避免不必要的多步模型调用。[Anthropic：Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)

避免为了路由每次额外调用一次 LLM：优先用已有会话状态、明确用户约束和可验证规则；不确定输入回到通用 Agent Loop。技能内容可按需由服务端准备，并对同一 Turn 已加载的技能去重，而不是强制模型先决定 `load_skill` 再重新调用模型。应保留动态技能的版本和审计信息。

当前 [运行时提示词](../../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/InMemoryAgentRuntimeConfigurationService.java)要求匹配技能时先加载；[工具工厂](../../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/SpringAiAgentToolCallbackFactory.java)仅按 Profile 和 `final_answer_only` 筛选。新增按阶段筛选应继续满足 Profile 授权，执行端再次复核。

### 2. 隐藏不可用工具，限制失败后的继续调用

工具集合应同时满足：Profile 允许、当前阶段需要、依赖已就绪。依赖状态使用短期缓存或熔断状态，不应为每次模型调用逐个同步探测服务。执行阶段仍需要处理依赖状态变化。

对明确的服务停机、配置错误等非瞬时失败，不应让模型重复调用同一目标；短暂错误采用有限重试预算。同一 Turn 可按工具与规范化参数记录调用，防止失败循环。无法获取事实时明确降级，不能编造商品、价格或库存。

当前 [AgentLoop](../../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/AgentLoop.java)已有最大循环数，最后一轮可限制为最终回答。建议增加更早的工具失败预算，不是笼统取消所有失败恢复。验收分别统计正常成功、降级回答和失败。

### 3. 精简提示词、schema 和结果

建议保留最少必要字段，合并重复规则；按场景减少工具，而不是只压缩工具说明。特别检查 A2UI schema 是否需要在普通追问中完整携带。

当前 [SpringAiAgentModelStreamClient](../../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/SpringAiAgentModelStreamClient.java)将 `available_skills`、工具结果和其余 Runtime context 编进 system prompt；Runtime context 又含技能提醒。应测量实际模板渲染后的 token 分布，避免重复列表和内部元数据占用模型输入。项目已实现 [AgentToolResultExternalizer](../../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/AgentToolResultExternalizer.java)，结果外置已有基础，应复用并量测，不能描述为尚未实现。

精简工具集合、保留高信号上下文，以及对大结果进行过滤、分页与截断，是官方建议；具体删减需用本项目任务验证。[Anthropic：Context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)、[Writing tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents)

## 第二优先级：应用额度与单卡服务调优

### 4. 提高默认额度，同时保留明确的排队边界

以模型流额度 16、32、64 分档复测；Active Loop 额度应容纳模型调用和工具等待，二者不是同一含义。有限排队、Turn 总截止时间、超载返回和取消传递一起设计，避免只把 200ms 等待改成很长。

同一 Session 的 Turn 继续串行，不应通过解除 [Session Execution Lane](../../../CONTEXT.md) 的串行约束提高并发。不同 Session 的排队可考虑按 Account 公平分配，避免少数账号占满额度。

旧样本 16 并发 P95 7.659 秒、32 并发 P95 11.390 秒，仅可作为复测起点，不是线上承诺。较大的额度主要提高接纳突发的能力；真正的吞吐提升需由后面步骤验证。

### 5. 改善已经启用的前缀缓存

将固定规则和稳定工具定义保持在可复用前缀；动态画像、工具结果、历史和请求信息放在后部。工具排序和序列化应稳定，并针对实际 chat template 检查匹配情况。APC 减少重复 prefill，不减少输出 token 的 decode 工作。[vLLM 0.24：Automatic Prefix Caching](https://docs.vllm.ai/en/v0.24.0/features/automatic_prefix_caching/)

仓库 [预热脚本](../../../java_agent/deploy/remote/model/vllm_prefix_warmup.py) 默认使用短英文提示词和专用 warmup context，不携带真实工具 schema，与实际中文 Agent 请求不同。它可用于服务和算子热身，但不能保证实际 Agent 的长前缀已经预热；即使提供系统提示词文件，也需完整请求模板匹配。已有压测指标证明 APC 已在工作，不应宣称缓存完全无效。

### 6. 扫参，而不是一次采用“最优参数”

在相同业务请求下分阶段尝试 `max_num_batched_tokens=2048/4096/8192/16384`，再围绕候选值尝试 `max_num_seqs=16/32/64/128`。先核对真实生效值与 chunked prefill 支持，避免两组参数全排列造成无意义负载。

vLLM V1 在支持时默认启用 chunked prefill；token budget 会改变 prefill/decode 的平衡，值更大并非对所有延迟指标更好。[vLLM 0.24：Optimization and Tuning](https://docs.vllm.ai/en/v0.24.0/configuration/optimization/)

纯文本运行、Qwen3.5 混合缓存限制、量化、推测解码与模型副本方案见 [vLLM 专项研究](vllm-optimization-research.md)。这些候选必须验证模型版本、后端、结构化工具输出和质量，不能承诺提升倍数。

如果产品确定不接收图片或视频，另可单独测试 `--language-model-only`。Qwen 的 4B 模型卡说明该参数跳过视觉编码器和多模态 profiling，为缓存释放空间；本项目启动脚本目前未设置。释放多少空间、能否提高此负载吞吐，需在当前安装版本实测。[Qwen3.5-4B 官方模型卡](https://huggingface.co/Qwen/Qwen3.5-4B)

## 验收方式

1. 先修复正式上下文预算与依赖就绪。按真实输入长度选择 8K/16K 等预算；扩上下文是兼容性修复，不是吞吐优化。给输出留出余量，覆盖长 Session 的 Effective Context。
2. 同一 GPU、同一权重、同一质量样本，逐项比较精简工具、简单路径、缓存布局、服务参数；每次只改一个主要变量。
3. 同时记录 Turn/s、模型调用/Turn、输入/输出 token、首可见回答、整轮 P95/P99、工具健康率、降级率、队列长度、cache hits/queries、preemption、GPU 与 Java 内存。
4. 除同步突发批次外，补充固定到达率测试，逐级提高 Turn/s，观察是否积压；先做短时筛选，再对候选配置做较长稳态验证。选择通过质量与延迟门槛的持续吞吐，不能以排队数量作为成果。
5. 最后加入网关、真实推荐/RAG、持久化与长 Session 重测。流式改善首可见等待，但不能单独算作吞吐增加；仍需遵守公开响应投影约束。

模型层未来增加独立 GPU 副本可提高推理吞吐；Agent 服务多实例另受 [ADR-0007](../../adr/0007-first-release-uses-one-active-agent-instance.md) 约束，需要会话执行 fencing 与持久化追加机制。不能直接复制多个 Agent 容器并共享 Session 写入。GPU 0/2 的既有训练资源不属于本方案可直接调配的空闲卡。
