# 模型服务下一轮优化：单次延迟与多请求吞吐（2026-10-11）

下一轮优先做实际前缀命中核查、批次预算单变量对照及入口容量治理。当前已有约束解码、编译、CUDA Graph 和前缀缓存，继续添加同类开关不能直接算优化；MTP、换注意力后端及跨卡扩容放在后面，依据测量结果决定。

本次只读核查和资料研究，没有修改正式部署，也没有执行负载测试。官方依据固定到当前 vLLM 0.24.0 的提交 `ee0da84ab`；最新 recipe 只作背景，不作为该版本与 RTX 4090 的支持证明。

后续执行已完成，见 [实测、回滚与最终状态](execution.md)。九轮隔离对照和三次正式切换没有找到满足“不退化”的推广版本，正式服务已恢复本轮开始时的配置与脚本；不要把下文建议解释为已经上线。默认批次 2048 与 async scheduling 开启已在等价隔离配置中核验，下文“待核验”描述的是研究形成时的状态。当前 PID、摘要及清理证据见 [最终只读审计](production-original-live-state.json)。

## 当前配置和证据边界

正式模型是 Qwen3.5-4B：96 个 MLP 投影使用 INT4 / INC / Marlin，注意力与 GDN 投影保留 BF16。GPU 1 与独立 BGE 共存；预算 50%，最大上下文 16384，调度序列上限 128，混合 KV / 状态缓存 3.99 GiB、106496 tokens。满 16K 容量估算 6.50 路，128 不能解释为 128 个满上下文请求。扩容主要增加容量，固定 128 tokens 耗时 875.81→878.23 ms 没有变快。[缓存扩容记录](../model-partial-quantization-20261011/cache-expansion.md)

2026-10-11 19:08:55（北京时间）只读检查确认 API PID 806733，当前采用 Inductor / `VLLM_COMPILE`、`FULL_AND_PIECEWISE`、普通注意力 `FLASH_ATTN`、Marlin；chunked prefill 和 prefix caching 开启，Mamba cache mode 为 align，speculative 配置为空，KV dtype 为 auto。编译范围包含 2048、图捕获尺寸到 256，但编译范围不是 scheduler 有效批次预算的证明；启动环境未指定 `max_num_batched_tokens`，该项与 resolved async scheduling 状态仍待核验。[当前运行证据](current-runtime.json)

累计 prefix queries 为 2106181 tokens、hits 为 1411344 tokens，约 67%；累计抢占为 0。这包括此前验收、重复探针、预热和保温，不能称为真实生产命中率，也不能证明目标并发下不存在容量瓶颈。后续必须观察业务窗口的计数增量。

## 两个目标应分别度量

| 目标 | 主要指标 | 优化判据 |
|---|---|---|
| 单次调用更快 | 排队、首 token 时间 TTFT、生成阶段 TPOT / ITL、完整完成时间 | 同输入、同输出工作量下，缩短实际调用；分别看冷缓存与热缓存 |
| 多请求整体更快 | 满足时延门槛的成功请求数 / 秒、有效输出 tokens / 秒、P95 时延、失败率 | 增加完成量且尾延迟、完整性不退化；排队不能持续增长 |

vLLM 当前源码已有 TTFT、TPOT、排队、prefill、decode、KV 占用、缓存 token、抢占等指标，可优先采集现有 `/metrics`。不要把第一个空 SSE role 帧当作内容 token，也不要把更长输出产生的 tokens/s 当作更多有效业务交付。[指标实现](https://raw.githubusercontent.com/vllm-project/vllm/ee0da84ab/vllm/v1/metrics/loggers.py)

## 建议优先级

| 顺序 | 单次调用 | 多请求 | 下一步 |
|---|---|---|---|
| P0 | 分清排队、prefill、decode | 找到吞吐拐点及排队来源 | 收集业务窗口增量，核对有效批次与 async 状态 |
| P1 | 提高实际前缀复用，复用稳定 schema 编译结果 | 减少重复 prefill 工作 | 按请求类型记录 cached tokens、未命中部分和 TTFT |
| P1 | 控制长 prefill 对已开始生成的请求的干扰 | 找到适合当前 INT4 的批次 | 先只扫 token 预算，保留模型、128 上限及 50% 预算 |
| P1 | 少排队、及时清理明确废弃的推理 | 有界入口与期限，避免无效请求占用 GPU | 验证取消传播、过载响应及取消后的资源释放 |
| P2 | 核对图覆盖、CPU 供给；低并发 MTP-1 | 有证据后调整图形状、共享 GPU 争用 | 隔离对照，每次只改变一个因素 |
| P3 | 当前卡饱和后减少排队 | 新增模型副本 | 需要另一块可分配 GPU，再做亲和分流和持续负载验收 |

### 1. 让已经开启的前缀缓存命中真实请求

APC 复用相同 token 前缀，减少 prefill；它不加速每个新输出 token 的 decode。优先核对模型服务收到的实际模板、tools 顺序、固定配置、历史序列和动态字段位置，记录每类请求的 cached tokens / prompt tokens。已有固定配置前置与预热应保留，先确认真实命中，再修复不必要的序列化差异；业务语义和可见内容保持原契约。[APC 原理与边界](https://raw.githubusercontent.com/vllm-project/vllm/ee0da84ab/docs/features/automatic_prefix_caching.md)

当前部分量化配置的长前缀直连探针中，首次请求首可见内容时间中位数约 184.42 ms，同一前缀重复为 58.15 ms。这说明已开启的缓存对该样本有效；首可见内容时间包含协议解析，不应直接替代引擎 TTFT，也不能将探针命中推广为所有真实请求命中。[正式探针证据](../model-partial-quantization-20261011/cache50-production-model.json)

GDN 的缓存有状态快照和块边界约束，命中结果须满足混合 cache 各组。该提交的 `MambaManager.find_longest_cache_hit` 已实现状态命中及对齐；设计文档仍有 Mamba prefix caching 尚在开发的旧描述，不能据此断言当前缓存无效。精细块配置须看实际 resolved block size，不能直接套纯 Transformer 的 16-token 分页经验。[状态缓存实现](https://raw.githubusercontent.com/vllm-project/vllm/ee0da84ab/vllm/v1/core/single_type_kv_cache_manager.py)

约束解码已有实现后，仍应检查动态 schema 是否持续触发编译。稳定 schema / tools 的内容及序列化形式有利于复用编译器缓存；不同商品枚举确实不同，不能为了缓存误复用旧约束。启动探针覆盖的 schema 不代表所有生产 schema 都已预热。[XGrammar 后端](https://raw.githubusercontent.com/vllm-project/vllm/ee0da84ab/vllm/v1/structured_output/backend_xgrammar.py)

### 2. 单变量调整批次预算，而不是继续增加并发上限

chunked prefill 已经开启。官方说明：优先安排 decode，把剩余 token 预算用于 prefill；较小预算通常减少 prefill 对 ITL 的影响，较大预算更有利于长输入 TTFT 与吞吐。因此“单次低延迟”和“多请求高吞吐”很可能对应不同最佳档位。[v0.24 调优说明](https://docs.vllm.ai/en/v0.24.0/configuration/optimization/#chunked-prefill)

建议先核对实际值，再在隔离实例显式试 2048、4096、8192 tokens 三档；第一轮固定 `max_num_seqs=128`，避免同时改变多个因素。覆盖短工具、真实约 6K 输入、接近 16K 的合法输入，以及长短混合请求。通过后才围绕优选值试 32 / 64 / 128 序列上限；更高上限增加可调度量，也可能增加排队尾延迟或 cache 抢占，并非越大越快。这些是候选实验，不是上线推荐值。

混合 cache align 模式要求 token 预算不得小于实际 block size；长 prefill 阈值同样要满足边界，该提交 V2 runner 不支持 align。不要同时改 runner、cache 模式与 batch 来寻求速度。[精确版本配置校验](https://raw.githubusercontent.com/vllm-project/vllm/ee0da84ab/vllm/config/vllm.py)

此前“纯文本 + 4096 tokens + 16 sequences”实验还同时改变了模型加载方式，且使用旧 BF16 与旧显存预算，未获得一致优势；它不能代替当前混合 INT4 配置的单变量扫描。[历史对照](../model-serving-tuning-20261011/README.md)

### 3. 有界入口和明确废弃推理的取消

调度序列上限不是 HTTP 入口队列上限。模型服务入口需要有限等待队列、请求期限与过载响应；对长请求可采用有配额的优先级，但必须防止长请求饥饿。上游期限已过、用户明确取消、请求已明确废弃时，应传播到模型推理并释放占用，减少无效 decode。[SchedulerConfig 的 policy 与序列限制](https://raw.githubusercontent.com/vllm-project/vllm/ee0da84ab/vllm/config/scheduler.py)

该版 `AsyncLLM.generate` 在推理生成器取消或退出时会 abort 请求；还需检查本项目 HTTP 客户端和代理是否传播取消。**客户端 SSE 短暂断开不自动等于 Turn 废弃**：必须保留仓库 Durable Session History / 完整交付契约，只有明确作废的模型请求才取消。验证重点是取消后的 running / waiting 回落及 cache 释放。[引擎取消实现](https://raw.githubusercontent.com/vllm-project/vllm/ee0da84ab/vllm/v1/engine/async_llm.py)

### 4. 已有 CUDA Graph / compile，重点看覆盖与供给

当前完整与分段图已运行。后续可观察真实 batch 的图命中、回退与 padding，再决定是否调整 capture sizes 或 compile ranges；扩大形状覆盖会增加图捕获成本和显存，缩小会牺牲某些请求形状。保留编译缓存主要改善重启初始化，不能当作稳态 decode 的新加速。当前版本 O3 等同 O2，单改优化级别没有依据。[CUDA Graph 设计](https://raw.githubusercontent.com/vllm-project/vllm/ee0da84ab/docs/design/cuda_graphs.md)、[当前优化等级定义](https://raw.githubusercontent.com/vllm-project/vllm/ee0da84ab/vllm/config/vllm.py)

若 GPU 有明显空洞，先核对 CPU 调度、tokenization、grammar mask 和网络等待，再考虑 CPU 亲和或 API 进程扩展。BGE 与 Qwen 同卡会竞争计算与带宽；应在 BGE 有实际请求的窗口量化争用后，再评估迁移 BGE 或各自限流。多开 Qwen GPU 进程重复装载权重和 cache，不能凭空增加算力；当前不优先做同卡多实例。CPU 资源不足会影响 vLLM 多进程供给，新增 API 服务同样有资源代价。[CPU 资源说明](https://docs.vllm.ai/en/v0.24.0/configuration/optimization/#cpu-resources-for-gpu-deployments)

## MTP、FP8 cache 与扩容的准确边界

### MTP：可以重新试，优先低并发

当前检查确认 `mtp_num_hidden_layers=1`，权重索引有 15 个 `mtp.*` 条目；部分量化导出的公开摘要也保留这些原 BF16 tensors，因此当前并非缺少 MTP 资产。[运行证据](current-runtime.json)、[部分量化 tensor 摘要](../model-partial-quantization-20261011/mlp_only-source.json)

该提交有 Qwen3.5 MTP 模型映射和 `mtp.*` 加载；APC 的 `mamba_cache_mode=all` 会被 MTP 明确拒绝，需 align 等支持路径，并核对 INT4 target 与 BF16 MTP predictor 的实际加载。权重存在只满足初步条件，当前量化组合的初始化、图、cache 占用和验收仍未知。[MTP 配置](https://raw.githubusercontent.com/vllm-project/vllm/ee0da84ab/vllm/config/speculative.py)、[Qwen3.5 MTP 实现](https://raw.githubusercontent.com/vllm-project/vllm/ee0da84ab/vllm/model_executor/models/qwen3_5_mtp.py)

strict structured 与 speculative 不是该版本的一概禁用组合：结构化管理器会为草稿位置生成 bitmask，并临时推进 / 回滚 grammar；async scheduler 同样处理等待结构化 token 的情况。默认 async 是否开启取决于 executor 与 speculative 方法；CPU n-gram 等方法存在限制。当前 resolved async 状态未知，不能宣称“现在加 async 就能提速”。代码存在组合路径不代表当前 `qwen3_xml`、XGrammar、流式、INC 与 hybrid cache 全组合已通过。[结构化投机 mask](https://raw.githubusercontent.com/vllm-project/vllm/ee0da84ab/vllm/v1/structured_output/__init__.py)、[AsyncScheduler](https://raw.githubusercontent.com/vllm-project/vllm/ee0da84ab/vllm/v1/core/sched/async_scheduler.py)

本项目旧 BF16 配对实验：172 tokens 为 1839.912→1700.164 ms，60 tokens 为 696.356→673.989 ms；真实 8 并发 MTP 中位约 11.46 秒，对照约 8.55 秒，输出长度有波动。因此优先做 MTP-1 的低并发隔离复测，再看 acceptance、固定长度 TPOT、额外显存和高并发退化；不直接上线，不外推旧模型结果。[既有 MTP 对照](../agent-llm-optimization-20261011/README.md#mtp-对照与失败实验)

### FP8 cache：当前后端不能直接增加开关

权重量化与 cache 量化独立。该版 GDN / Mamba state dtype 只支持 auto、FP32、FP16、BF16；`--kv-cache-dtype fp8` 不会把全部 3.99 GiB 混合 cache 减半，分页对齐也影响容量收益。[CacheConfig](https://raw.githubusercontent.com/vllm-project/vllm/ee0da84ab/vllm/config/cache.py)、[GDN state dtype](https://raw.githubusercontent.com/vllm-project/vllm/ee0da84ab/vllm/model_executor/layers/mamba/mamba_utils.py)

当前 CUDA `FLASH_ATTN` 的 FP8 KV 支持判定要求 FA3 和 SM90 家族，RTX 4090 是 SM89，不符合。另一个 `FLASHINFER` 后端声明支持 FP8，但 kernel block sizes、hybrid 分页和图组合仍需核对，不能仅换后端就认定成功。FP8 缩放还需代表数据校准和工具质量验收。它更适合容量瓶颈已明确时做后续隔离实验，目前优先级低于批次扫描。[FLASH_ATTN 支持判定](https://raw.githubusercontent.com/vllm-project/vllm/ee0da84ab/vllm/v1/attention/backends/flash_attn.py)、[FLASHINFER 能力与页大小](https://raw.githubusercontent.com/vllm-project/vllm/ee0da84ab/vllm/v1/attention/backends/flashinfer.py)、[KV 校准说明](https://docs.vllm.ai/en/v0.24.0/features/quantization/quantized_kvcache/)

### 需要更多 GPU 时先比较模型副本

4B 已能装入单卡。若当前卡在目标业务负载下饱和，优先比较另一块独立 GPU 的同模型副本，按负载和尽力缓存亲和分流；正确性不能依赖 Session 一定命中某副本。GPU 是否可分配需重新核对，不能占用现有训练任务。模型副本扩容不要求同时复制业务 Agent。[DP 部署](https://raw.githubusercontent.com/vllm-project/vllm/ee0da84ab/docs/serving/data_parallel_deployment.md)

TP 增加逐层通信，对当前小模型没有必然优势；先与每卡副本比较。P/D 分离需要多个实例及缓存传输，官方将其定位为独立控制 TTFT / ITL、改善尾 ITL，并明确不以吞吐提升作保证；在单卡 4B 上增加复杂度与重复权重，暂不优先。[并行策略](https://docs.vllm.ai/en/v0.24.0/configuration/optimization/#parallelism-strategies)、[当前版本 P/D 说明](https://raw.githubusercontent.com/vllm-project/vllm/ee0da84ab/docs/features/disagg_prefill.md)

## 下一轮实验的产出要求

1. 保留当前模型、严格约束、原工具与完整回答验收；不通过压低预算、强制提前结束或修改规划职责制造提速。
2. 冷 / 热缓存分别报告。先少量固定输入、固定生成工作量对照，再覆盖真实输入与长短混合持续到达；测试样本保留输出长度和正常结束率。
3. 单变量测试批次预算，之后才改变序列上限、图配置、MTP 或后端；每次记录 resolved 配置、初始化后的 cache 容量和共同环境。
4. 报告成功请求 / 秒、P50 / P95 TTFT、TPOT、完成时间、排队、抢占与业务窗口缓存增量。区分仅闭环并发探针和持续负载，不把 32 条短请求全通过解释为容量 SLA。
5. 只推广同时满足完整性、工具语义和性能目标的候选；给出负载范围及恢复入口。具体候选和边界见同目录 [实验计划](experiment-plan.json)。
