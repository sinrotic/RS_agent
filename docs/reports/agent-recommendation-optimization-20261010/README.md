# 单轮推荐优化实现与 GPU 测量

后续已补齐真实业务完整链路和浏览器验收：[完整推荐流程实测](../agent-recommendation-e2e-20261010/README.md)。明确首轮“推荐鼠标”优化接口约 1.24–1.42 秒，浏览器最终显示约 1.37–1.90 秒，300ms 目标仍未达到；原 Agent 8 并发还出现 5 个约 30 秒超时。以下模型阶段数据保留原实验范围，不能替代该完整链路结果。

已实现首轮明确需求的直接推荐路径、模型计算缓存、HTTP 连接复用、分段观测，以及可配置的 BGE 半精度和批次大小。Java 构建完成，最新回归 299 项通过、1 项跳过，另有 3 项 Python HTTP 契约测试通过。直接推荐和计算缓存尚未启用，服务器正式服务与模型配置保持原状态。

完整推荐在 8 并发下 P95 不超过 300ms 的目标尚未达到。GPU 1 实验中，更新后的 BGE HTTP 路径单请求约 68ms，但 8 并发最慢约 560ms；这些数据不包含召回、训练排序、交付与会话持久化、浏览器展示。不能将模型阶段耗时当作完整回答耗时。

## 已实现的行为

直接推荐仅接受首轮的完整有限语法，例如“推荐耳机”“请推荐100美元以内的耳机”。支持耳机、双肩包、键盘、鼠标和笔记本电脑的明确叶子类目；配件或未知叶子类目回退。带预算时必须配置经数据来源核实的目录币种，并逐项检查真实价格。理由仅描述已核验的品类和预算，不生成未经证实的商品特性。

后续轮次、已有 checkpoint、额外属性、否定、比较、模糊或冲突预算、未知币种、非空 A2UI 状态、自定义提示词、Profile、skill、hook 或 Loop 均回到原 Agent。推荐降级、空候选、缺少价格、超预算或混合交付 ID 时，把同一批候选交给 Agent，不重复检索或登记交付。

两条路径共用原 Loop 的最终答案处理、公开投影、Session 串行、停止和最终持久化。重试复用原轮次与 card_set_id。内部价格验证依据不增加到公开 recommended_items 结构。不同用户仍分别读取偏好、执行训练排序并创建各自交付，未缓存最终推荐结果。

缓存保存精确输入的 embedding 与 BGE 分数。键包含模型版本、查询、实际送入的候选 ID 和商品文本；商品文本、查询或版本改变时不复用。设置 TTL、每类独立估算字节上限、同键计算合并和不可变返回值。异常或不完整评分不会入缓存。embedding 权重估算包含装箱 Float 的开销。BGE 缓存当前以整批候选为键，候选集合或顺序变化会未命中，尚未实现逐对评分复用。

HTTP adapters 共用 JDK HttpClient 连接池，并保留原连接和读取超时。真实 Java HTTP 测试验证两个 adapter 复用同一个连接且请求内容正确。BGE 的连接等待队列从 Python 默认的 5 提高到 128；这不是 GPU 的执行并发数。运行时仍使用原推理锁，尚未实现跨请求动态微批。

BGE 增加 device、dtype、重排批次与 PyTorch 显存上限配置，默认仍为原精度、批次 8。半精度在 CPU 转换后再搬入 GPU，避免临时加载全精度 GPU 权重。配置较大批次遇到 CUDA OOM 时，缩小批次重新计算全部候选，最低退回 8；没有减少候选或伪造评分。CPU 模式不暴露 GPU。

Agent 观测包含入场排队及权限恢复、上下文恢复与路由、推荐、答案处理、最终提交和总耗时。入场失败也记录总耗时。Recommend 观测包含 embedding、向量搜索、目录事实、COLD/DeepFM、BGE、交付和推荐 trace。日志不记录用户或查询；已有 Micrometer 注册时还可读取 `cache.gets`、`cache.evictions` 等缓存指标，缓存名为 `recommend_query_embedding` 和 `recommend_bge_scores`。

## 真实模型测量

2026-10-10，GPU 1 为 RTX 4090，原 Qwen/vLLM 仍驻留但实验期间空闲。GPU 0、2 的训练继续运行。探针只在临时目录和 localhost 临时端口运行，未安装或重启正式服务。PyTorch 显存分配上限为 GPU 1 总显存的 0.11，正式模型没有改成半精度或重新量化。

| 范围 | 观测耗时 |
|---|---|
| CPU、4 线程、真实 BGE 权重，查询向量加 96 个短候选重排 | 7937ms |
| GPU 1 FP16、批次 8，查询向量加 96 个短候选，内部方法调用 | 约 179ms |
| 上述内部方法 8 并发，共享推理锁 | 311–1431ms |
| GPU 1 FP16、批次 64、连接队列 128，更新后的真实 HTTP，96 个短候选 | 67.7–69.2ms |
| 上述真实 HTTP，8 个不同查询同时请求，未缓存 | 226–560.5ms |
| 上述真实 HTTP，96 个 1200 英文字符候选 | 319.7ms，触发批次 64 → 32 的显存保护 |

纯重排实验还测得：将 8 组请求共 768 对短文本合并成一次 predict，批次 8、32、64 分别需要约 1230、415、275ms。这是未来跨请求微批的方向；正式 HTTP 实现尚未合并这些请求，也未把这个数字作为当前在线表现。

小样本中，FP16 与 CPU 原精度的查询向量余弦为 0.99999946，96 个评分最大绝对差为 0.000136。它只能说明这批合成样本接近，不能替代真实目录排序质量门禁。商品文本为合成短文本或重复英文描述，未覆盖真实文本长度分布、中文长描述、复杂 Agent 与推荐同时占用 GPU 的情况。每档样本较少，不报告可靠的生产 P95 或最大 Agent 容量。

优化后的 HTTP 探针峰值 allocated 为 2447.5MiB，reserved 为 2568MiB，另有 CUDA 驱动等开销。退出后 GPU 1 显存恢复至原约 20257MiB，vLLM `/health` 返回 200，正式 BGE service 仍为 inactive。

## 配置与回滚

Agent 和 Compose 已提供以下设置：

```dotenv
RS_AGENT_DIRECT_RECOMMENDATION_ENABLED=false
RS_AGENT_CATALOG_CURRENCY=
RS_AGENT_PERFORMANCE_OBSERVATION_ENABLED=false
RS_RECOMMEND_PERFORMANCE_OBSERVATION_ENABLED=false
RS_RECOMMEND_INFERENCE_CACHE_EMBEDDING_VERSION=
RS_RECOMMEND_INFERENCE_CACHE_RERANKER_VERSION=
RS_RECOMMEND_INFERENCE_CACHE_MAX_BYTES=33554432
RS_RECOMMEND_INFERENCE_CACHE_TTL_SECONDS=300
```

缓存版本留空即关闭。开启前应固定权重、精度及文本预处理版本；模型、精度或预处理更新时，修改对应版本并重启 Recommend，不能让同一版本指向变化的权重。字节预算是每类缓存的保守估算，并非整个进程的硬 RSS 限额。BGE 配置样例见 [bge-runtime.env.example](../../../java_agent/deploy/remote/model/bge-runtime.env.example)。GPU 示例只是实验参数，不能直接替代真实工作负载门禁。

关闭直接推荐并留空两个缓存版本、重启相关服务即可回到原业务路由与计算方式；BGE 恢复 `dtype=auto`、`batch_size=8`。连接池和较大连接队列不改变推荐策略。回滚不改写数据库事实、交付或训练权重。

## 剩余验收与下一步

后续隔离验收已接通真实目录、Milvus、训练排序、Scylla/Redis/MySQL、Gateway 与浏览器 hydration，核验历史恢复和反馈归因，并在临时 16384 上下文下完成原 Agent 对照。原 4096 上下文实际使完整请求失败。测试后基础服务恢复原停机状态，GPU 1 恢复原参数；正式服务没有启用快速路径。币种、广泛的推荐相关性、复杂需求和完整故障/取消门禁仍未全部验证。

下一步依据完整链路分段数据优先减少重复恢复和持久化往返，保留 authoritative 最终提交边界，再加入有界的跨请求微批、按文本长度选择安全批次，以及快速路径的独立额度。停止在下游检索开始前的登记、独立截止时间和共享计算等待者的单独取消尚未实现；当前保留原停止语义，不宣称全链路取消已经完善。

只有真实目录质量、反馈、历史、取消、复杂请求回退以及 8 并发完整结果门禁通过，才能有限启用。缓存命中与未命中、新查询与重试、短文本与长文本必须分开报告，失败和降级计入总体指标。当前不承诺所有单轮对话 300ms。

## 复现与证据

Java 使用 JDK 21，Maven heap 1536MiB、测试 heap 1024MiB：`mvn -pl rs-service-agent,rs-service-recommend -am package -DargLine=-Xmx1024m -q`。Python 契约检查：`python -m pytest tests/test_bge_runtime_http.py -q`。JAR 摘要与测试数见 [validation.json](validation.json)。

模型探针需要服务器已有 venv 和本地权重，参数为 `--runtime`、`--embedding`、`--reranker`、`--output`。GPU 探针固定仅使用 GPU 1，并在显存不满足预算时提前失败。运行时源码由仓库复制到独立临时目录，未覆盖正式部署目录。

- [CPU 原始数据](bge-cpu.json) 与 [探针](bge_cpu_probe.py)。
- [GPU 精度、批次和长文本数据](bge-gpu1.json) 与 [探针](bge_gpu_probe.py)。
- [更新后的 BGE HTTP 数据](bge-runtime-http.json) 与 [探针](bge_runtime_http_probe.py)。
- [默认连接队列为 5 的 HTTP 对照](bge-runtime-http-backlog5.json)。该样本曾出现约 1 秒额外等待，增大队列后的一轮复测未再出现；样本不足以证明所有尾延迟均由连接队列导致。
- [原实施方案](../../superpowers/plans/2026-10-10-single-turn-recommendation-latency.md)。
