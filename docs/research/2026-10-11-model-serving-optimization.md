# 模型服务低延迟优化研究

检索日期：2026-10-11。对象是现有 Qwen3.5-4B 模型服务、vLLM 0.24.0、XGrammar 0.2.3、单张 RTX 4090 24GB。以版本固定的官方源码、官方模型卡与文档为依据；最新文档只用于识别候选方向，不据此承诺本机速度。本文的建议没有修改或重启在线模型。

## 结论与执行顺序

优先优化真实 Agent 请求的输入长度、稳定前缀、输出长度与工具轮次，再用实测选择低延迟调度参数。当前已经使用 prefix caching、chunked prefill、torch.compile 与 CUDA Graph，不能把这些功能再次计为新增收益。量化在本仓库已有失败与不可复现记录，不能为了节省权重显存直接切换正式服务。

建议顺序是：建立模型与 Agent 两层基线 → 缩短有效上下文和不必要轮次 → 修正真实请求预热 → 调度扫参 → 纯文本加载 → MTP 小规模对照 → 满足质量门槛后才重新考虑量化或增加模型副本。

| 分类 | 手段 | 本项目的处理 |
|---|---|---|
| 可以先做 | 分阶段计时、真实负载样本、记录输出完整性 | 不重启模型即可建立基线 |
| 可以先做 | 简化提示、动态内容后置、工具顺序稳定、输出按场景限长 | 先比较渲染后 token 与回答质量，保留既有权限和公开投影 |
| 可以先做 | 入口队列上限、排队期限、超载拒绝、取消失效请求 | 额度按满足 P95 的吞吐设定，不能无限堆积 |
| 需要 A/B | 真实 payload 预热、定时 keepalive | 比较冷启动、热缓存、重启和长期运行；不要只看 probe 通过 |
| 需要 A/B | `max_num_batched_tokens`、`max_num_seqs`、纯文本加载 | 在隔离实例一次改变一个因素 |
| 需要 A/B | MTP、n-gram、指定 AWQ/GPTQ/FP8 检查点 | 同时验收格式、内容、工具、吞吐与时延 |
| 当前不推荐 | 沿用既有失败 FP8 配置上线、4090 当前 FlashAttention 直接加 FP8 KV | 已有质量/复现失败，且后端有硬件限制 |
| 当前不推荐 | 对 4B 单卡服务直接套多卡 TP、P/D 分离、CPU offload | 当前没有相应瓶颈证据，会引入通信或搬运开销 |

## 2026-10-11 基线采样时的运行现场

本节由本次只读现场核查提供，与 10 月 9 日隔离实验分别记录。旧的 `vllm-constrained-decoding.log` 不代表采样时进程。完整采集值见 [environment.json](../reports/model-serving-optimization-20261011/environment.json)。采样后发现另一 MTP 试验正在切换原进程，详情见文末状态记录；下表及速度成绩只对应采样时的非 MTP 配置。

| 项目 | 当前确认值 |
|---|---|
| 模型与精度 | Qwen3.5-4B，BF16，`quantization=None` |
| 服务 | `127.0.0.1:18082/v1`，模型名 `qwen35-4b` |
| 最大上下文 / 显存预算 | 16384 / `gpu_memory_utilization=0.78` |
| 缓存与调度 | prefix caching 开启，chunked prefill 开启，KV dtype `auto` |
| 图与内核 | `VLLM_COMPILE` / Inductor，`FULL_AND_PIECEWISE`，FlashAttention |
| 当前启动日志 | `context-optimization-20261010/model.log` |
| 内存记录 | 权重 8.61 GiB，KV 预算 7.38 GiB，197470 token；GPU 1 当前总占用约 21637 MiB |
| Hybrid 缓存 | Mamba `align`，attention block size 528；图捕获尺寸最高 512 |
| MTP 权重 | 本地 `text_config.mtp_num_hidden_layers=1`，权重索引有 15 个 `mtp.*` 条目 |

197470 token 与 16K 条件下约 12.05 倍的理论缓存并发是容量估计，不是每秒可完成请求数，也不是 Agent Turn 的性能保证。显存预算、缓存池容量与 `nvidia-smi` 总占用有不同口径；不要把 0.78 直接当成总显存占用百分比。

10 月 9 日既有实测仍可作为风险证据，但上下文、预算、实例、工具路径均不同，不与今日值直接拼成提速结论。[历史并发研究](../reports/agent-capacity-20261009/vllm-optimization-research.md)、[历史量化验收](../reports/agent-quantization-20261009/README.md)。

## 已有应用实现，避免重复建设

工作区代码已有以下优化，但不能把代码存在当作当前线上入口全部启用：

- `local-qwen` Profile 默认开启精简工具 schema，普通模型调用输出上限 1024，最终回答上限 4096；这些都是上限，不表示每次实际生成这些 token。[Profile 配置](../../java_agent/rs-service-agent/src/main/resources/application-local-qwen.yml)。
- `SpringAiAgentModelStreamClient` 在精简模式下已将固定输出规则和运行配置移到动态证据之前，并关闭 thinking。后续应针对实际渲染后的工具与上下文验证共享前缀，而非重新声称首次开启这些优化。[客户端](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/SpringAiAgentModelStreamClient.java)。
- 首轮、明确且满足商品事实门禁的需求已有直接推荐与 LLM 合成路径；复杂输入保留 Agent Loop。优化多轮调用应在此基础上比较，而非放宽门禁换取短回答。[直接推荐](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/AgentDirectRecommendation.java)。
- Agent 默认最多 8 路模型流、额度等待 200ms；这不是 vLLM 的最大批次或已测 GPU 容量。[应用配置](../../java_agent/rs-service-agent/src/main/resources/application.yml)。

本次模型主机的 `18104` 提示接口不可达，未启动或切换业务应用，因此没有采集今日完整 Agent / 推荐 / 数据库 / 前端的延迟。历史存储与 BGE 优化证据可另行使用，但不能把它们的成绩当作本次 Qwen API 的成绩。

## 先定义“快速”

模型 API 和 Agent 的完成时间需要分别测量：一次 Turn 可能包含多次模型调用、检索、技能加载与公开响应投影。模型很快但工具轮次多，用户仍会等待。

| 指标 | 含义 | 应如何使用 |
|---|---|---|
| TTFT | 发请求到首个有效输出 token 的时间 | 判断输入处理、排队与 prefill 的延迟 |
| TPOT | 排除首 token 后的平均每输出 token 时间 | 在相同输出长度下比较 decode；公式约为 `(总耗时 − TTFT)/(输出 token 数 − 1)` |
| ITL | 相邻输出事件/输出 token 的间隔分布 | 判断流式过程中是否卡顿；不是 TPOT 的完全同义指标 |
| E2E | 发请求到有效回答完成的时间 | 同时受首 token、输出长度和工具轮次影响 |
| P50/P95/P99 | 上述指标的分位数 | P95 为 95% 样本不超过该时间，小样本的 P95 不稳定 |
| 吞吐 / goodput | 每秒完成数量 / 同时满足质量与时限的完成数量 | 全局 tok/s 高不代表单用户等待短，降级和不完整回答不能计为质量合格 |

vLLM 官方 benchmark 分别报告 TTFT、TPOT、ITL 与 token 吞吐，并允许固定输入输出长度、并发或请求速率；不要混用离线 throughput 数字和线上体验。[v0.24 benchmark 指南](https://raw.githubusercontent.com/vllm-project/vllm/v0.24.0/docs/benchmarking/cli.md)。

客户端首个 SSE 事件可能只有角色、工具名或空增量。首 token、首个完整工具参数、首个公开 `answer_block`、Turn 完成应各自计时。保持 [ADR-0012 公开响应投影](../adr/0012-public-agent-response-projection.md)，不要为了提前显示而公开未经校验的半截 JSON。

采集 `/metrics` 中的运行/等待请求、KV 使用率、prefix hits/queries、抢占、排队、prefill、decode 和 E2E 指标；指标名与单位以实际 endpoint 为准。命中比例使用本批增量，避免拿进程生命周期的累积计数冒充本次负载命中率。[v0.24 metrics 设计](https://raw.githubusercontent.com/vllm-project/vllm/v0.24.0/docs/design/metrics.md)、[计数实现](https://raw.githubusercontent.com/vllm-project/vllm/v0.24.0/vllm/v1/metrics/loggers.py)。

## 优先减少真实请求工作量

以下是结合本项目链路提出的工程建议，具体收益必须测量：

1. 固定系统规则与工具定义保持简洁且稳定；按 Runtime Profile 只提供已授权、该场景确实需要的能力，避免重复说明和长示例。工具裁剪改变行为，需用真实购物、普通建议和澄清样本验收。
2. 动态状态、时间、用户偏好和本轮检索证据尽量后置；工具 JSON 的顺序、描述与字段序列化保持稳定。不能为缓存而删除必要权限或 grounding 信息。
3. Tool Result 只提供决策所需的结构化摘要，截去无关大字段，商品事实保留来源。历史压缩只在 Safe Compaction Boundary 生效，保留工具配对和 Durable Session History。[ADR-0003](../adr/0003-compaction-only-at-safe-model-call-boundaries.md)、[ADR-0004](../adr/0004-auditable-lossy-context-truncation.md)。
4. 短意图提取、澄清、最终回答设置不同的合理输出预算；减少重复开场、复述和无需执行的工具调用。降低 `max_tokens` 只是上限限制，若模型本来提前结束，不会自动提速；过小会截断结构化结果。
5. 简单确定性任务可以由已有规则处理；是否增加小模型路由应按质量收益和额外常驻成本判断。真正独立的只读检索可以在业务层并行，但不能破坏同一 Session 的 Turn 串行语义。[ADR-0006](../adr/0006-serialize-turns-within-each-session.md)。

当前请求关闭 thinking 可减少不需要的推理生成，但应检查全部调用入口的 `chat_template_kwargs` 一致，不能只依赖某个客户端。官方模板会根据该参数改变生成前缀。[Qwen 官方模板](https://huggingface.co/Qwen/Qwen3.5-4B/blob/main/chat_template.jinja)。

## 前缀缓存与预热

APC 复用相同 token 前缀的 prefill，不消除新输出的 decode。固定说明重复但 token 前缀不同，依然不能命中；全块匹配及模型、LoRA、多模态等附加条件也影响复用。[APC 功能说明](https://docs.vllm.ai/en/v0.24.0/features/automatic_prefix_caching/)、[hash/block 设计](https://raw.githubusercontent.com/vllm-project/vllm/v0.24.0/docs/design/prefix_caching.md)。

官方 Qwen 模板把 `tools` 写在系统提示之前。因此只用相同系统文字预热、却不提供真实 tools，可能在前部就分叉；工具集合或排列变化也影响后续前缀。这个结论由模板顺序与 APC 的精确 token 匹配规则共同推得，需对比本地实际模板的渲染 token。[Qwen 模板源码](https://huggingface.co/Qwen/Qwen3.5-4B/blob/main/chat_template.jinja)。

现有预热脚本可获取 Agent 提示，失败时有 fallback；它还构造 warmup 状态/说明，且没有完整真实工具定义。因此它能预热算子、检查可用性，也可能命中一部分公共 token，但不能保证真实 Agent 长前缀已预热。现场提示 URL `18104` 不通，应该从真实调用构造一份脱敏、无副作用的代表 payload 再验证。来源：[仓库预热脚本](../../java_agent/deploy/remote/model/vllm_prefix_warmup.py)。

Qwen3.5-4B 混合 Gated DeltaNet 与完整注意力；v0.24 实现明确拒绝 Mamba `all` 模式，要求 `align`。不要用普通 Transformer 的“每 16 token 精细命中”假设解释当前 528 的块。定时预热不保证缓存永久保留，还会占用一次模型工作；以命中 token 增量和真实 P95 验证，而非单看开关。[Qwen3.5 实现](https://raw.githubusercontent.com/vllm-project/vllm/v0.24.0/vllm/model_executor/models/qwen3_5.py)。

## 连续批处理与调度调优

vLLM 调度会持续把新请求加入可用 batch；chunked prefill 把长输入拆分，优先安排 decode，并把剩余 token 预算用于 prefill。较小 `max_num_batched_tokens` 通常降低已有 decode 被 prefill 拖慢的 ITL；较大值倾向于改善长输入 TTFT 和吞吐。两者互有取舍，官方“小模型大 GPU 的吞吐建议”不等于单 4090 的低延迟最优值。[v0.24 调优文档](https://docs.vllm.ai/en/v0.24.0/configuration/optimization/)。

先记录运行时有效 `max_num_seqs`、`max_num_batched_tokens` 与异步调度状态，再设置候选矩阵。建议围绕当前值，试 token 预算 2048/4096/8192/16384 和 sequences 8/16/32/64/128 中的少量组合；这是实验候选，不是上线默认值。用同样的短输入、真实 6K～16K Agent 输入和长短混合流量比较，保留满足 P95 的吞吐最高配置。

`max_num_seqs` 是调度限制，不是可靠的入口队列上限。过小会把等待移到队列，过大可能牺牲单请求时延；入口应同时有有界队列、期限和取消机制。低延迟目标必须有负载范围，不能保证任意并发下都快。源码还区分流式发送 interval 与异步调度，参数存在不意味着当前已开启或兼容全部特性。[v0.24 SchedulerConfig](https://raw.githubusercontent.com/vllm-project/vllm/v0.24.0/vllm/config/scheduler.py)。

Qwen align 校验要求 `block_size <= max_num_batched_tokens`；设置长 prefill 阈值时也不得小于 block size，且 v0.24 的 V2 runner 不支持 align。当前块为 528，不能把预算降到 512，也不能顺手打开 V2 runner。[版本固定配置校验](https://raw.githubusercontent.com/vllm-project/vllm/v0.24.0/vllm/config/vllm.py)。

## 编译、图与纯文本加载

现有 `torch.compile` 与 `FULL_AND_PIECEWISE` 已启用。保留有效编译缓存主要改善启动时间；正式压测要等模型初始化、图捕获和代表请求预热完成，再分别报告冷/热状态。不要为了启动快而默认 `--enforce-eager`，这会改变运行优化路径。[v0.24 torch.compile](https://raw.githubusercontent.com/vllm-project/vllm/v0.24.0/docs/design/torch_compile.md)。

CUDA Graph 模式和 capture size 影响内存、捕获时长与覆盖形状；当前最高 512 不代表请求全部能享受 full graph。不同后端的 prefill、decode、投机 decode 支持不同，减少捕获上限可能省空间但也可能损失高并发表现，须独立对照。[CUDA Graph 设计](https://docs.vllm.ai/en/v0.24.0/design/cuda_graphs/)。

纯文本业务可在隔离实例试 `--language-model-only`，跳过视觉编码器与多模态 profiling。官方 4B 模型卡提供该路径；它最直接减少无用加载/显存，未必直接降低文本 decode 延迟，不能预报节省数值。若需要图片能力，应另行路由或保留多模态实例。[Qwen3.5-4B 官方说明](https://huggingface.co/Qwen/Qwen3.5-4B)。

## 投机解码的可用边界

| 方法 | vLLM 0.24.0 能确认的事实 | 本项目建议 |
|---|---|---|
| MTP | 配置有 Qwen3.5 MTP 映射，源码有独立 predictor 和 `mtp.*` 加载 | 本地权重元数据已满足初步条件；从 1 个 speculative token 开始隔离验证 |
| n-gram | 原生 proposer 从提示中的重复 token 片段提出草稿，不需另装草稿权重 | 抽取/复述任务可试；开放购物建议重合低时可能无收益 |
| 独立 draft / EAGLE | 框架支持但需要匹配的额外检查点和运行成本 | 当前 4B 单卡服务低于前两项优先级 |

支持配置不等于当前严格工具 + XGrammar + streaming + hybrid cache 已通过验收。MTP 要记录草稿 acceptance、额外显存、TTFT、TPOT、负载下 throughput；分别测 APC 开/关，不能直接删去现有缓存配置。[SpeculativeConfig](https://raw.githubusercontent.com/vllm-project/vllm/v0.24.0/vllm/config/speculative.py)、[Qwen3.5 MTP 实现](https://raw.githubusercontent.com/vllm-project/vllm/v0.24.0/vllm/model_executor/models/qwen3_5_mtp.py)、[n-gram 指南](https://docs.vllm.ai/en/v0.24.0/features/speculative_decoding/n_gram/)。

另一个不能遗漏的变量是异步调度：v0.24 配置校验会对普通 CPU `ngram` 禁用默认 async scheduling，强制组合时会报不兼容；`ngram_gpu` 是不同路径，V2 runner 同样不支持这两种 proposer。因此 n-gram A/B 必须记录最终调度状态，不能把开关加入后视作“无额外代价”。[v0.24 组合校验](https://raw.githubusercontent.com/vllm-project/vllm/v0.24.0/vllm/config/vllm.py)。

投机解码适合中低 QPS、访存受限的 decode；收益受草稿命中率、硬件与流量影响。官方最新 Qwen3.5 recipe 推荐低并发 MTP-1，并提出关闭 prefix caching 的对照方向，但其验证是大型多卡 397B 环境；这个推荐不能外推为 4090/4B 的速度保证。[v0.24 投机解码说明](https://raw.githubusercontent.com/vllm-project/vllm/v0.24.0/docs/features/speculative_decoding/README.md)、[官方 recipe 及验证范围](https://github.com/vllm-project/recipes/blob/main/Qwen/Qwen3.5.md)。

## 量化与显存：不能把省空间当作必然更快

Ada 硬件兼容 AWQ、GPTQ、Marlin 和 FP8 实现；FP8 计算支持 SM89。但硬件可用不保证特定 Qwen hybrid 检查点的格式、内核、精度与 strict-tool 行为正确。AWQ/GPTQ INT4 通常量化权重，激活与状态未必量化；校准、分组、反量化开销和 batch 大小都会改变速度。[v0.24 硬件表](https://docs.vllm.ai/en/v0.24.0/features/quantization/)、[FP8 指南](https://raw.githubusercontent.com/vllm-project/vllm/v0.24.0/docs/features/quantization/llm_compressor/fp8.md)、[GPTQModel 与内核](https://raw.githubusercontent.com/vllm-project/vllm/v0.24.0/docs/features/quantization/gptqmodel.md)。

GDN 一些投影不能任意套 blockwise FP8，模型敏感层排除规则必须核对。[v0.24 GDN 源码](https://raw.githubusercontent.com/vllm-project/vllm/v0.24.0/vllm/model_executor/layers/mamba/gdn/qwen_gdn_linear_attn.py)。

现有量化实验发现：FP8 结构探针仍可 7/7，通过格式不能证明工具链和回答正确；出现额外工具调用、失败委派或只有开场语。分层 W8A16 在隔离实例有改善，但正式重启后不稳定，最终 `promote=false` 回退 BF16。所有旧提速数字仅属于特定实验，当前不推荐把同配置再次作为默认优化。[完整量化验收与回退证据](../reports/agent-quantization-20261009/README.md)。

FP8 KV 与 FP8 权重是两回事。Mamba/GDN 状态的 dtype 配置只含 auto/FP32/FP16/BF16；将 attention KV 设成 FP8 不会让整个混合缓存减半，分页填充也影响实际收益。[CacheConfig](https://raw.githubusercontent.com/vllm-project/vllm/v0.24.0/vllm/config/cache.py)。

更具体的限制是：v0.24 CUDA `FLASH_ATTN` 的 FP8 KV 检查要求 FA3 和 SM90。当前 RTX 4090 是 SM89，不能保留当前后端就直接加 `--kv-cache-dtype fp8`。换到其他兼容后端必须重新验证混合分页、图、工具质量与缩放校准，不在本次线上尝试。[FlashAttention 支持判定](https://raw.githubusercontent.com/vllm-project/vllm/v0.24.0/vllm/v1/attention/backends/flash_attn.py)、[KV 量化与校准](https://docs.vllm.ai/en/v0.24.0/features/quantization/quantized_kvcache/)。

## 扩容、流式与验收

当前模型已有独立 GPU 1，不能干扰 GPU 0 的训练任务。若单卡在目标负载下排队成为瓶颈，可验证空闲 GPU 2 的独立模型副本；模型副本按稳定前缀/Session 做尽力亲和有利于缓存，但正确性不能依赖亲和。单卡能放下 4B 时，先比较每卡副本，TP 要计入通信成本。[v0.24 DP 部署](https://raw.githubusercontent.com/vllm-project/vllm/v0.24.0/docs/serving/data_parallel_deployment.md)。

模型副本扩容与 Java Agent 多实例是不同决策；后者受单活约束，不能直接复制 Agent 容器上线。[ADR-0007](../adr/0007-first-release-uses-one-active-agent-instance.md)。虚拟线程减少阻塞线程开销，但不能新增 GPU 算力；保留模型流背压，不用无限 streams 冒充容量。[ADR-0008](../adr/0008-blocking-model-streams-run-on-virtual-threads.md)。

流式可以缩短用户看见内容的等待，不会减少 GPU 完成所有 token 的工作。若最终结构必须完整校验才能发布，可展示真实执行状态，或经既有 `emit_ui` 发布完整合法块；不可直接泄漏内部原始流。渲染、代理 buffering 与 HTTP 连接复用应计入端到端测量，再确认是否是瓶颈。

后续每项 A/B 都保持同一任务、工具定义、温度和输出预算，先检查答案完整、事实正确、无失败工具、无异常额外轮次，再比较性能。覆盖冷/热缓存、进程重启、长短混合、持续请求速率及并发 1/4/8/16/32 等目标档位；不要只跑无限速闭环批量。报告成功率、有效 Turn/s、P95 TTFT/公开首块/E2E、每 Turn 模型调用和 token、抢占及缓存增量。少量 smoke 只证明可用，不证明 P95 容量或稳定提速。

## 今日基线与后续实测

测试脚本在模型主机经 loopback 访问已运行服务，不加载额外权重，不重启模型，不清空共享前缀缓存。开始与结束的 running/waiting 请求数均为 0；这只是两个采样点，不能证明整个过程独占流量。共 32 个请求：28 个结构化请求通过字段、类型、预算、类目及完整结束检查；4 个固定 128 token 的合成解码请求故意以 `length` 结束，只用于速度测量，不计为完整业务回答。

| 场景 | 样本数 | 首个内容/参数片段中位数 | 完整返回中位数 | 输入 / 输出 token |
|---|---:|---:|---:|---:|
| 短 JSON 提取，顺序请求 | 6 | 54.79ms | 616.91ms | 79 / 58 |
| 严格 named 工具提取，顺序请求 | 6 | 204.27ms | 769.29ms | 378 / 73 |
| 同一工具，并发最多 4、共两批 | 8 | 300.93ms | 936.99ms | 378 / 73 |
| 固定 128 token 合成解码 | 4 | 51.07ms | 1301.99ms | 35 / 128 |

工具测试使用独立的 `extract_shopping_intent`，不是完整 Agent 的 `emit_final_answer` / A2UI 工具集。首个工具参数片段之前可能已经生成工具协议前缀，所以 204.27ms 不能直接与 JSON 的 54.79ms 比成模型内核下降，也不能称为用户看见回答的 TTFT。首次 schema/工具调用另有预热记录，不混入表中的顺序稳态样本。

三组约 2712～2714 输入 token 的长前缀，开头使用不同随机标识，分别测首次与相同 payload 重复请求：

| 配对 | 首次首内容 | 重复首内容 | 首次完整 | 重复完整 |
|---|---:|---:|---:|---:|
| 1 | 194.25ms | 61.07ms | 787.58ms | 654.90ms |
| 2 | 191.83ms | 60.81ms | 747.64ms | 614.38ms |
| 3 | 192.33ms | 65.21ms | 786.94ms | 658.60ms |

每组的生成 token 数相同。这个小样本支持稳定真实前缀能降低 prefill 等待；它没有改变部署，也不代表完整回答提速三倍。首内容改善约 127～133ms，完整耗时改善幅度更小，因为后续 decode 仍要执行。APC 不加速新 token 的生成，与官方功能边界一致。[APC 官方说明](https://docs.vllm.ai/en/v0.24.0/features/automatic_prefix_caching/)。

固定长度样本按 `(E2E − 首内容)/(输出 token − 1)` 估算 decode 约 101.5 token/s；这不是逐 token ITL 测量，也不能外推到长上下文或高并发。按这个量级直观估算，数百 token 的结构化回答仍会有秒级生成工作，因此要减少实际生成的冗余文字和字段，不能仅调低 `max_tokens` 后宣称加速。

两批并发 4 的总耗时 1.8788 秒，不是持续开放到达负载，不据此报告最大容量。所有场景样本少，报告中位数及原始数据，不报告生产 P95/P99。缓存指标增量也包含本脚本各场景与可能的后台预热，不用于严格归因。

完整证据：[baseline.json](../reports/model-serving-optimization-20261011/baseline.json)、[environment.json](../reports/model-serving-optimization-20261011/environment.json)、[可复跑脚本](../reports/model-serving-optimization-20261011/benchmark.py)。测量脚本的初版将“通勤背包”与“背包”做等值比较而误判；随后接受同一类目的自然表达，再冻结脚本运行上面的 32 请求，未通过修改提示或填造结果绕过模型检查。

## 具体实施与验收顺序

1. **先比较真实 payload，而非调整引擎开关。** 从现有客户端构造澄清、普通建议、明确推荐、复杂比较四类样本，记录完整工具定义渲染后的输入 token、真实输出 token、模型调用次数。检查现有 compact schema 与直接推荐路径是否在目标应用入口启用。维持 16K 窗口及完整输出余量，不退回与完整 Agent 不兼容的 4K。
2. **修正代表请求预热与稳定前缀。** 复用实际工具列表、chat template 和 thinking 参数；动态 Session/商品字段后置。用无副作用的脱敏模型请求预热，再以真实 Agent 样本测新增命中和首公开块时间。继续保留模型格式与业务事实校验。
3. **逐项进行引擎 A/B。** 先固定 BF16、上下文和输出预算，试纯文本加载；再扫少量 token budget 与 sequence 组合。当前 argv 没有显式 batch 参数，安装版 `arg_utils.py` 的 4090/OpenAI 服务默认分支为 2048 token / 256 sequences，但这是源码推断，需拿到运行时 resolved config 才能称为最终生效值。[v0.24 默认推导源码](https://raw.githubusercontent.com/vllm-project/vllm/v0.24.0/vllm/engine/arg_utils.py)。
4. **只对合格候选追加解码优化。** MTP 从 1 个 speculative token 做隔离对照，验证严格工具、流式、APC、重启与完整回答。当前 FP8 失败配置不再直接推广；另选具体量化检查点时仍需相同质量门槛。
5. **最后按目标负载配置额度或副本。** 测并发 1/4/8 的短任务及实际长请求，再做有界、固定到达率的稳态测试。只有等待主导且单卡 goodput 已达平台时，才讨论第二张 GPU 副本。复杂工具与数据库耗时独立计时；不能承诺所有购物回答都在数百毫秒完成。

以上是基于今日证据排序的实施方案。引擎参数、MTP、量化和副本部署仍是本报告尚未验证收益的候选，本次研究没有切换在线模型或发布新的业务配置。

## 采样后的状态变化

原非 MTP 进程在北京时间 2026-10-11 10:26:41 收到 SIGTERM 并退出，发生于上述基线请求完成之后。10:27:56 的只读核查发现同一 `18082` 端口的新 vLLM 进程，其参数包含 `speculative_config={"method":"mtp","num_speculative_tokens":1}`，日志位于另一试验目录；当时 HTTP 尚未监听。该进程不是本次研究创建或修改的，未干预其启动，也未自动启动第二个模型争用 GPU。

这意味着本文不能保证读者查看时的服务状态，也不能把后续 MTP 实验的性能或质量与本报告基线混用。原配置、基线与此后状态分别保存，后续实验应重新确认运行时参数、模型就绪和质量门槛。[采样后状态证据](../reports/model-serving-optimization-20261011/final-state.json)。
