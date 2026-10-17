# GPU 1 模型服务并发优化检索

检索日期：2026-10-09。对象为单张 RTX 4090、Qwen3.5-4B、vLLM 0.24.0。只使用官方模型卡、官方文档和版本固定的官方源码；以下都是研究与试验建议，没有修改或重启模型服务。

## 判断与优先顺序

现有实测中，104 并发达到 3.633 完成轮次/秒、P95 28.157 秒；192 并发达到 3.839 轮次/秒、P95 49.006 秒。继续放大入口额度主要增加排队，不能据此认为吞吐会同步提高。有效结果要求临时 16K 上下文，原先 4K 配置不能承载完整 Agent 提示和工具定义。详见[压测报告](README.md)。

模型侧优先尝试：**纯文本加载、稳定真实请求前缀、调度参数扫参**。量化、FP8 KV、MTP 有模型与后端兼容约束，放在后续独立实验中；没有证据支持承诺提升倍数。

## 已启用与可试项目

| 项目 | 当前证据 | 建议与验收方式 |
|---|---|---|
| Prefix caching | 启动脚本已显式启用；104 档原始计数 hits/queries 为 3726624/5198843，约 71.68% | APC 已发挥作用，接下来改善前缀布局，分别测冷/热缓存，避免把收益重复计入 |
| 纯文本模型加载 | 当前脚本没有 `--language-model-only` | 在保持工具解析、结构化输出不变的隔离实例中加入，比较实际权重/缓存容量与吞吐 |
| Chunked prefill | V1 在可用时默认开启，但脚本没有明确设置调度预算 | 先记录实际启动日志，再扫 `max_num_batched_tokens` 和 `max_num_seqs`，选择满足时延目标的配置 |
| 显存预算 | 压测为 0.85；临界档只出现少量抢占 | 独占 GPU 时可小步试 0.90，与基线比较；只有缓存压力下降且好吞吐提高才保留 |
| 横向模型副本 | 本次只有 GPU 1 可用 | 将来有空闲 GPU 后，以独立模型副本与负载分配作为扩容候选，单卡上复制进程不能新增 GPU 算力 |

71.68% 是 vLLM 指标的计数命中比例：hybrid 模型的 queries 与 prompt token 总数存在不同计数口径。它不是 71.68% 的整轮延迟或输入计算已被消除。

Qwen3.5-4B 是 Gated DeltaNet 与完整注意力交替的 hybrid 模型；官方模型卡明确提供 `--language-model-only`，用于跳过视觉编码器及多模态 profiling。当前业务为文本加工具调用，因此该项是优先实验候选；实际释放多少显存需实测。[Qwen 官方 4B 模型卡](https://huggingface.co/Qwen/Qwen3.5-4B)

APC 复用相同前缀的 prefill 结果，不加速新 token 的 decode。因此，将固定系统指令、稳定排序的工具 schema 放在稳定前缀，将用户状态和动态证据放在后部，是本项目可验证的设计建议；不能仅凭已开启开关判断最终收益。[vLLM 0.24.0 APC](https://docs.vllm.ai/en/v0.24.0/features/automatic_prefix_caching/)

本地静态检查发现，预热默认使用较短英文系统提示，附加 `warmup:true` 上下文，而且没有真实 tools definitions。它可以预热算子和检查服务可用，但不保证真实中文 Agent 请求的前缀命中。即使提供系统提示文件，也需要比较完整 payload 经模板渲染后的 token 前缀。来源：[预热脚本](../../../java_agent/deploy/remote/model/vllm_prefix_warmup.py)、[启动脚本](../../../java_agent/deploy/remote/model/start_qwen35_4b_vllm.sh)。这项静态发现与真实压测已有 APC 命中并不矛盾。

Chunked prefill 将 prefill 切块并与 decode 混批。较小 token 预算通常利于 ITL，较大预算可能利于 TTFT/吞吐；官方针对小模型大 GPU 的吞吐建议不能直接当作本卡最优值。显存不足导致抢占时，可增加缓存预算或降低 batch 限额。[vLLM 0.24.0 调优说明](https://docs.vllm.ai/en/v0.24.0/configuration/optimization/)

建议先固定 `max_num_seqs=128`，试 token 预算 2048、4096、8192、16384；取较好预算后再试 sequences 32、64、128。这是待测矩阵，不是推荐直接上线的参数。Qwen hybrid 的 align 模式要求实际 block size 不大于 token 预算，且 v0.24.0 的 V2 model runner 不支持 align，不能同时套用所谓新版 runner 优化。[v0.24.0 配置校验源码](https://raw.githubusercontent.com/vllm-project/vllm/v0.24.0/vllm/config/vllm.py)

## 模型与后端兼容性

| 方案 | 能确认的支持边界 | 对本项目的结论 |
|---|---|---|
| Hybrid prefix cache | Qwen3.5 实现明确拒绝 `mamba_cache_mode=all`，要求 `align` | 不照搬其他 Mamba 模型的 `all` 参数；调整布局与预算时保留 align 约束 |
| AWQ/GPTQ/FP8 权重量化 | Ada 硬件支持相关实现；Qwen GDN 投影已有量化路径，但部分投影有额外限制 | 不能以硬件支持推断任意量化检查点可用；需具体检查点加载、工具质量及吞吐验证 |
| FP8 KV | full-attention KV 与 GDN 内部状态使用不同 dtype 配置 | 不能声称整个缓存减半；当前 attention 后端及 hybrid 分页约束必须核验 |
| MTP / speculative decoding | v0.24.0 已含 Qwen3.5 MTP 架构与配置映射 | 有代码支持不代表本地权重和缓存组合已验收；优先级低于减少 Agent 调用与 batch 调优 |

Qwen3.5 的 `all` 拒绝逻辑和 `align` 要求来自版本固定的实现，优先于通用文档对其他架构的默认值。[v0.24.0 Qwen3.5 实现](https://raw.githubusercontent.com/vllm-project/vllm/v0.24.0/vllm/model_executor/models/qwen3_5.py)

Ada 支持 AWQ、GPTQ、Marlin 与 FP8 W8A8，这只是硬件兼容表，不是 Qwen3.5-4B 指定检查点的端到端保证。[vLLM 0.24.0 量化硬件表](https://docs.vllm.ai/en/v0.24.0/features/quantization/)

GDN 源码将量化配置传给多个投影层，也明确标注 ba 投影不支持 blockwise FP8，并处理 AWQ/GPTQ 的 Marlin 分片限制。选择 FP8/AWQ/GPTQ 检查点时，应核实哪些敏感层被排除、配置格式是否匹配，保留 BF16 质量基线。[v0.24.0 GDN 量化源码](https://raw.githubusercontent.com/vllm-project/vllm/v0.24.0/vllm/model_executor/layers/mamba/gdn/qwen_gdn_linear_attn.py)

FP8 KV 可节省注意力缓存，缩放值与校准会影响精度；没有校准时可能使用默认 scale，不能只看启动成功。[vLLM 0.24.0 KV 量化说明](https://docs.vllm.ai/en/v0.24.0/features/quantization/quantized_kvcache/)

v0.24.0 的 `MambaDType` 仅接受 auto、float32、float16、bfloat16，区别于支持 FP8 的 attention cache dtype。因此 FP8 KV 不会自动量化 GDN 状态；真实收益取决于 hybrid 缓存布局。[v0.24.0 CacheConfig 源码](https://raw.githubusercontent.com/vllm-project/vllm/v0.24.0/vllm/config/cache.py)

关键后端限制：v0.24.0 `FLASH_ATTN` 的 CUDA FP8 KV 路径要求 FA3 和 SM90/Hopper。RTX 4090 属 Ada，不能在保留此后端时简单加 `--kv-cache-dtype fp8`。能否换到兼容后端，要用本地 CUDA/内核版本和 Qwen hybrid 完整 smoke 验证；本次没有运行这个组合。[v0.24.0 FlashAttention 源码](https://raw.githubusercontent.com/vllm-project/vllm/v0.24.0/vllm/v1/attention/backends/flash_attn.py)

MTP 配置已把 qwen3_5 映射到专用 MTP 架构，模型实现需要加载相应 `mtp.*` 权重；不能复制其他 Qwen 模型的方法名后视作可用。[v0.24.0 speculative 配置](https://raw.githubusercontent.com/vllm-project/vllm/v0.24.0/vllm/config/speculative.py)、[Qwen3.5 MTP 权重加载](https://raw.githubusercontent.com/vllm-project/vllm/v0.24.0/vllm/model_executor/models/qwen3_5_mtp.py)

vLLM 官方 Qwen3.5 recipe 把 MTP-1 用于低并发时延，并建议关闭 prefix caching，指出负载下可能牺牲吞吐。该 recipe 验证硬件为大型多卡配置，不能外推为单 4090/4B 性能保证。APC 与 MTP 组合本次未验证，分别测更可靠。[官方 Qwen3.5 recipe](https://github.com/vllm-project/recipes/blob/main/Qwen/Qwen3.5.md)

## 扩容与指标

DP 将模型复制到不同实例/GPU，每个引擎维护独立缓存；支持 dense 模型并可按正在执行、排队数量及缓存状态分配请求。Qwen 4B 已能装入单卡，因此未来扩容优先比较每卡一个副本；TP 的跨卡通信成本需与吞吐收益一起测。[vLLM 0.24.0 DP 部署](https://docs.vllm.ai/en/v0.24.0/serving/data_parallel_deployment/)

流式返回改善用户看到首段回答的时间，但不能凭此断言 GPU 每秒完成更多轮次。本项目 answer_block 目前通常整段就绪后展示，首可见回答与模型 TTFT 需要分开采集。vLLM benchmark 支持 TTFT、TPOT、ITL、E2EL 和带 SLO 的 goodput；下一轮同时记录这些指标与 Agent 完整轮次指标。[vLLM 0.24.0 benchmark 参数](https://docs.vllm.ai/en/v0.24.0/cli/bench/serve/)

每项实验保持同一模型权重、实际工具 schema、样本和输出预算，一次只变一个因素；先跑结构化输出及工具调用 smoke，再测独占 GPU 下的 16/32/64/96 档和固定请求速率稳态。记录模型调用/轮、输入与输出 token、队列长度、缓存命中、抢占、显存、完成率和工具失败率。只把满足约定 P95 和质量门槛的完成轮次计入有效吞吐。

本次无法确认：本地权重是否含完整 MTP 权重、指定量化检查点质量、FP8 替代后端在本机的可用性、改参数后的持续容量。所有这些项都需要单独实测；现有 104 档仍只是先前隔离短轮次链路的结果。
