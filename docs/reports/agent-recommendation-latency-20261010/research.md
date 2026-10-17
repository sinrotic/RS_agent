# 单轮对话推荐 300ms 可行性调查

日期：2026-10-10。仅核对项目记录、ADR 和官方文档；没有运行 GPU 测试、改动服务代码或部署。

## 判断

既有约 5 秒的结果不是理论下限，也不是在线商品推荐延迟：它来自普通建议与澄清混合请求、8 并发、内存 Session 和固定候选的隔离测试，未包含真实在线推荐、数据库和网关。完整轮次、完整商品卡片、生成解释、模型首 token 是不同指标。[压测范围](../agent-capacity-20261009/README.md)、[BF16 对照](../agent-quantization-20261009/README.md)。

300ms 可以作为明确需求的单轮推荐待测目标，现有证据不能承诺实现或质量无回归。让当前完整 Agent 每次执行模型、可能的工具循环并生成自由文本，不能根据已有结果保证 300ms。将商品卡片先返回、解释随后生成，仅改善首次结果可见时间，不能算完整回答在 300ms 内完成。

## 官方机制能解决什么

| 机制 | 作用与边界 | 官方依据 |
|---|---|---|
| Automatic Prefix Caching | 复用相同前缀的 KV 计算，减少 prefill；不减少生成新 token 的 decode 时间。适合稳定系统提示与重复 Session 前缀。 | [vLLM APC](https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/) |
| 关闭 thinking | Qwen3.5 可用 `chat_template_kwargs.enable_thinking=false` 直接回答，减少思考内容生成；不能由开关推断业务质量等价。 | [Qwen3.5-4B 官方模型卡](https://huggingface.co/Qwen/Qwen3.5-4B#instruct-or-non-thinking-mode) |
| Speculative decoding / MTP | 通过草稿和验证减少每 token 延迟，官方定位于低至中 QPS、内存受限工作负载。采样算法有无损性质，但硬件数值与批次仍可能导致输出差异；速度需本机验证。 | [vLLM 投机解码与无损边界](https://docs.vllm.ai/en/latest/features/speculative_decoding/) |
| 延迟优先推理配置 | 官方 Qwen recipe 说明 MTP 可以改善每 token 延迟，同时可能降低高并发吞吐。该 recipe 的主要配置针对 397B 多卡环境，不能直接当作本项目 4B、RTX 4090 的收益保证。 | [vLLM Qwen recipe](https://docs.vllm.ai/projects/recipes/en/latest/Qwen/Qwen3.5.html#latency-focused-serving) |

本项目既有压测已经开启 APC、关闭 thinking，不能将这两项重复算作新增收益。[环境记录](../agent-capacity-20261009/README.md)。量化最终未通过正式重启后的完整回答与工具健康验收，已回退；因此不能把量化当作已实现且无质量影响的加速项。[量化验收](../agent-quantization-20261009/README.md)。

生成长度本身也需要预算：假设一次实际生成 100 个 token，仅生成就要在 0.3 秒内达到约 333 token/s，且尚未给排队、prefill、召回和网络留下时间。这只是算术示例，不是本机速度预测；长解释不能只靠减少闲置保证完成目标。

## 适合本项目的设计推断

现有流程先取得推荐条目，再运行 Agent Loop；非空聊天查询已走语义召回。推荐服务已有查询相关性、偏好与训练排序路径。可研究给意图和约束充分明确的请求增加固定业务路径：复用现有 Recall Source、Ranking Route、Catalog Item hydration，经公开投影返回 `product_cards`，理由依据实际匹配事实生成短模板。复杂约束、比较、澄清和自由解释保留当前 Agent 路径。[查询路由 ADR](../../adr/0015-query-aware-agent-recommendation.md)、[训练排序 ADR](../../adr/0021-trained-ranking-serving.md)、[公开投影 ADR](../../adr/0012-public-agent-response-projection.md)。

这是待验证设计，不能将现有通用 `reasonHint` 视为与模型解释等价，也不能宣称路由无损。若使用结果缓存，必须隔离 Account / Profile User、权限、Session Preference、Preference Version、查询与约束，以及推荐产物版本；价格、库存等商品事实需刷新。缓存命中 300ms 与未命中新请求 300ms 必须分别统计。

验收应在真实服务上分别记录完整卡片、完整解释和完整 Turn 的 P50/P95，注明并发、冷暖状态、超时与降级率，并检查约束遵守、排序、商品事实、解释依据及复杂请求的回退正确性。收到确认、首 token 或先出的卡片不能替代完整结果指标。
