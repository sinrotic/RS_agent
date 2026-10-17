# RS Agent vLLM model service

2026-10-11 后续批次、MTP、前缀与保温候选已完成对照，但没有通过全部正式门槛，当时已恢复原配置和脚本，见 [实测与回滚报告](../../../../docs/reports/model-serving-next-optimizations-20261011/execution.md)。`VLLM_EXTRA_WARMUP_CONCURRENCY` 与 `VLLM_RECHECK_IDLE_PER_PREFIX` 是实验能力，分别默认 0 / false，正式服务仍未启用；不能直接启用后称作已验证的加速方案。

## 部分缓存命中与内核预热（2026-10-12）

GPU 1 当前 INT4 模型已在空闲时完成新版补热，原模型进程、参数及现有轻量保温进程保留。新版 Python 预热脚本和 Bash 启动器已原子安装，部署 `.env` 启用 `VLLM_KERNEL_WARMUP=true`、`VLLM_KERNEL_WARMUP_BATCH_SIZES="1 4 8 16"`，下一次正常启动沿用新流程。本轮未重启正式模型；启动顺序与失败时不发布 ready 的检查使用占位进程完成，真实空 Triton 缓存验证使用 GPU 2 临时实例。

启动在原真实前缀与结构化输出探针之后，增加 6608 tokens 的长输入及共享前 5000 tokens、长度余数为 0/1/2/4/8 的部分命中输入。随后对 1/4/8/16 路短输入各生成两 token，覆盖 prefill 和一次 decode。合成输入直接访问模型 `/v1/completions`，没有用户身份或工具执行；全部成功后补回受保护文件里的真实 messages/tools 前缀，最后才发布 ready。KV 前缀缓存和内核编译缓存是两回事；此流程覆盖本轮发现的路径，不保证所有新长度、模型或工具格式都无需编译。

新增开关示例默认 false；只有这个已验证部署设为 true。开启时每个合成批次和每条真实前缀执行前检查运行/等待请求指标，忙或指标不可用即失败退出，手动补热可在空闲后重试。已发出的批次无法因为新业务到达而撤回，空闲检查仍有竞态。定时 `--keepalive` 始终只执行原轻量前缀逻辑，即使环境启用了内核预热也不重复这些批次。当前进程空闲补热可使用同目录 `.env` 导出的环境运行 `python3 vllm_prefix_warmup.py --kernel-warmup --skip-ready-wait --delay-after-warmup-sec 0`，无需更换模型。

隔离模型的已知冷路径首 token 由 442ms 变为预热后的 134ms，正式网关单请求本轮均值 191ms → 173ms（各 8 条）；4/8 路并发首 token 没有稳定下降。完整推荐仍约 2.09 秒，键盘类目的既有 BGE 排序降级仍存在。范围、全部样本、服务身份核验和备份位置见 [预热接入与实测报告](../../../../docs/reports/agent-kernel-warmup-20261012/README.md)。

## 服务优化与预热（2026-10-11）

GPU 1 正式服务已通过隔离对照后启用 `VLLM_JSON_COMPACT_OUTPUT=true`，在 XGrammar 配置中添加 `disable_any_whitespace`。这是普通 `response_format=json_schema` 的排版约束；当前版本的 strict 工具使用另一种 structural-tag grammar，不能据此推断工具调用也会减少输出 token。相同短 JSON 样例的完成时间中位数由 616ms 降到 438ms，工具样例仍约 768ms。样本、启动与重启验证见 [优化执行报告](../../../../docs/reports/model-serving-tuning-20261011/README.md)。

正式 `.env` 还配置 `VLLM_WARMUP_CONCURRENCY=8`、`VLLM_WARMUP_ONLY_WHEN_IDLE=true` 与本机受保护的 `VLLM_WARMUP_PAYLOAD_FILE`。启动先预热实际 messages、tools、tool_choice 和 chat_template 参数，再执行七种结构化探针与一组八路 named-tool 并发探针；全部完成才写 ready。定时保温读取运行及等待请求指标，忙或无法核验指标时跳过，不会在保温入口额外生成一次。空闲检查与业务到达之间仍存在竞态，不能当作严格资源隔离。

预热文件为 1 至 8 个记录的 JSON 数组，例如：

```json
[{"profile":"shopping","payload":{"messages":[{"role":"system","content":"与业务一致的固定系统提示"},{"role":"user","content":"脱敏的测试输入"}],"chat_template_kwargs":{"enable_thinking":false}}}]
```

有工具的路径应同时包含真实工具 schema 与工具选择设置。脚本保持这些模板输入，只统一模型、温度、单结果、非流式和输出 token 上限，并删除另一个输出上限及最少 token 设置；正式预热仅生成 1 token，不执行工具。显式配置文件损坏时启动失败，不回退到别的提示词。请只在服务器保存脱敏测试请求，文件权限设为 0600，不提交请求正文；提示词或工具 schema 更新后同步刷新文件。候选商品枚举或历史变化时只有相同 token 前缀可复用，预热不保证所有请求完整命中缓存。

新增 `VLLM_LANGUAGE_MODEL_ONLY`、`VLLM_MAX_NUM_BATCHED_TOKENS`、`VLLM_MAX_NUM_SEQS` 与 `VLLM_SPECULATIVE_CONFIG` 作为受控实验入口，示例默认关闭或留空。本次测试中纯文本模式及 `4096 tokens / 16 sequences` 批次限制没有稳定收益，正式部署未启用；MTP 和 FP8 也未由本次优化启用。原 BF16、视觉能力、16K 上下文及 GPU 1 的 0.78 显存比例保留。

更新运行中的 Bash 启动器应先上传到另一个文件，再用同目录原子替换；不要原地覆盖，避免正在读取脚本的进程发生错位。部署前备份并核对文件摘要、进程身份、GPU 和空闲状态；部署后检查 ready、结构化输出报告及完整实际工具参数。

## GPU 1 与 BGE 共用显存的上下文配置（2026-10-10）

完整 Agent 的工具定义、历史与最终输出预算需要较大的窗口。4K 配置曾因输入 2897 加输出预算 1200 超过 4096 而拒绝普通推荐；当前启动器拒绝小于 16K 的配置。BF16、工具约束与既有上下文压缩规则保持原设置。

另外，真实复杂推荐的强制最终回答曾达到普通 1200 tokens 上限，返回 `finish_reason=length` 和截断的工具 JSON。Agent 的 `rs.agent.model-provider.final-answer-max-tokens` 可单独扩展受约束的 `final_answer_only` 调用；`local-qwen` profile 默认 4096，验收环境也明确设置 `RS_AGENT_FINAL_ANSWER_MAX_TOKENS=4096`。普通工具调用继承原预算，快速推荐路径没有模型调用。通用部署默认 0，即沿用提供方预算；不会降低已有更大预算，也不会移除工具、商品或 UI 能力。预算是上限，正常提前结束的回答不填满额度；完整普通流程仍需要实测耗时。

当前 GPU 1 的正式本地模型部署使用 `CUDA_VISIBLE_DEVICES=1`、`VLLM_MAX_MODEL_LEN=16384`、`VLLM_GPU_MEMORY_UTILIZATION=0.78`，为独立 BGE FP16 留出显存。原先 0.85 不是共享 GPU 场景的合适容量分配。设备与比例是本次服务器的实测配置，不作为其他机器的默认值。启动日志的 197470 tokens 缓存容量仅表示缓存空间，不等同于业务能达到的并发或延迟。

启动时预热与七种结构化输出探针均通过后才创建 ready 文件。修改真实模型 `.env` 后通过 `run_qwen35_4b_vllm.sh` 启动，使重启沿用同一配置；不要用仅覆盖进程环境的临时参数代替持久配置。仍需以普通推荐、多轮和反馈后的完整业务验收确认模型路径可用。

## FP8 权重量化（2026-10-09）

启动器支持 `VLLM_QUANTIZATION` 与 `VLLM_QUANTIZATION_CONFIG`。默认 `auto` 沿用原权重配置；JSON 以单个参数传给 vLLM，不通过 shell eval。当前 Qwen3.5-4B 的 FP8 候选使用 vLLM 0.24.0 在加载本地 BF16 权重时进行 per-channel FP8 转换，激活动态量化，无需下载社区权重或额外校准数据。磁盘原权重不变。

以下 per-channel 配置已经出现实际 Agent 工具路径回归，作为诊断示例保留，不能作为通过验收的生产配置。JSON 探针成功不足以证明工具选择或回答质量正常。

本次分层 W8A16 虽通过隔离压测，正式重启后回答或工具路径仍回归，最终已恢复原 BF16 部署，没有启用量化。所有 FP8 配置都需要覆盖实际 Agent、完整回答及重启后热缓存状态，不应直接复制示例到正式 `.env`。

```bash
VLLM_QUANTIZATION=fp8_per_channel
VLLM_QUANTIZATION_CONFIG='{"ignore":["lm_head","re:.*visual.*","re:.*linear_attn.*","re:.*self_attn.*"]}'
VLLM_MAX_MODEL_LEN=16384
```

该配置保留 Gated DeltaNet、完整注意力、视觉模块及输出层的原精度，主要量化 MLP；Embedding、归一化及未匹配的非线性模块也不会因此变成 FP8。KV 缓存 dtype 保持原配置。`fp8_per_channel` 的实际支持以已安装的 vLLM 版本为准，不能将它当作通用旧版本参数。

完整 Agent 请求超过原 4K 上下文，因此 `.env.example` 调整为 16K；新环境仍应依据输入、历史与输出预算选取合适值。回退到 BF16 时必须同时设置 `VLLM_QUANTIZATION=auto` 并清空 `VLLM_QUANTIZATION_CONFIG`，否则配置字段仍可能启用在线量化。

FP8 首次启动会编译新的计算图和内核，预热等待建议使用 `VLLM_READY_TIMEOUT_SEC=600`。ready 文件仍在结构化输出探针全部通过后创建；增加等待时间不会绕过验收。

启用前后均运行结构化输出探针，再对比相同 Agent 样本的工具健康率、回答质量、P95 与完成轮次/秒。显存预分配总量可能保持不变，应从启动日志比较模型加载占用与可用缓存容量。FP8 是否改善吞吐需实测，不能由权重位数推算。

`app/agent_quantization_model.py` 核验 GPU 1、备份原脚本与配置、停止空闲模型并切换对照实例；只有验收文件明确通过才允许推广。该辅助脚本为本次服务器布局编写，不是通用多 GPU 部署工具。结果及范围见 [量化验收报告](../../../../docs/reports/agent-quantization-20261009/README.md)。

启动器在收到停止信号时清理模型和预热子进程，防止预热期间留下孤立进程。可在 Linux 执行 `python3 test_vllm_launcher.py`，用占位进程验证量化 JSON 参数传递及停止行为，不加载 GPU 模型。

## 多路召回候选服务（2026-09-13）

`prepare_multi_recall.py --config <build-config.json> --output <新版本目录>` 从已有 train-only 正式产物流式构建 SQLite 候选索引。构建配置包含版本、各路 manifest、文件 glob、kind（edges/user/category/popular），以及 `category_profiles`。原始文件逐个记录 SHA256；输出目录必须不存在，构建完成且 quick_check 通过后才写 serving manifest。大文件仅在远程部署主机处理，不传回本机。

`multi_recall_runtime.py --directory <版本目录>` 只读打开索引，在内部 `172.21.0.1:18118` 提供 `/health` 和 `POST /internal/recall/multi`。请求包含 `profile_user_id`、最新在前的 `history_item_ids`、`sources`、`limit`；响应按来源返回真实 ID/分数和版本号。客户端使用 Content-Length JSON，请求体上限 32KB，历史最多 80 项，每路最多 120 项；运行时同时最多处理 8 次查询。

运行时仅依赖 Python 标准库。将脚本部署到 `~/RS_agent_java/model_deploy/`，安装 `rs-multi-recall-runtime.service` 后执行 `systemctl --user daemon-reload` 和 `systemctl --user enable --now rs-multi-recall-runtime.service`。当前单元引用 `multi_recall_20260913` 目录，内存上限 512MB，异常退出后自动恢复。启动前确认 manifest 完成，不能对正在服务的 SQLite 文件执行导入或更新。

设置 Recommend 的 `RS_RECOMMEND_MULTI_RECALL_ENABLED=true`、`RS_RECOMMEND_MULTI_RECALL_BASE_URL=http://172.21.0.1:18118`、`RS_RECOMMEND_MULTI_RECALL_VERSION=multi_recall_20260913`，重建该容器即可接通；关闭开关可退回双塔+BGE原路由。`python -m unittest test_multi_recall_runtime.py` 验证种子衰减、去重、已见过滤、冷启动和来源校验。`app/multi_recall_acceptance.py` 验证隔离 Java 与真实索引、BGE、Catalog 的完整调用链。

## 已训练双塔运行时（2026-09-13）

`two_tower_runtime.py` 使用真实 epoch 5 用户塔参数和归一化商品向量执行既有 queryv2。此服务使用 CPU，不占用 BGE GPU；依赖 NumPy，建索引与 ANN 验证另需 pymilvus。大文件转换和建索引应在部署服务器执行。示例路径为当前服务器路径，首次部署到其他主机时需相应调整 systemd 单元与监听地址。

```bash
~/RS_agent_remote/.venv/bin/python prepare_two_tower_serving.py \
  --checkpoint /mnt/data/luo/RS_agent_remote_storage/outputs/two_tower_sparse_aware_serial_checkpoints/checkpoints/epoch_5 \
  --output ~/RS_agent_java/data/models/two_tower_epoch5_20260913 \
  --collection rs_agent_two_tower_epoch5_20260913
```

该命令拒绝覆盖已有集合；当前部署已完成，不要重复执行。将运行时复制到 `~/RS_agent_java/model_deploy/two_tower_runtime.py`，将 `rs-two-tower-runtime.service` 放入 `~/.config/systemd/user/`，执行 `systemctl --user daemon-reload` 和 `systemctl --user enable --now rs-two-tower-runtime.service`。用户 linger 已启用；新主机需另外配置，才能在未登录时启动用户服务。

健康检查为 `http://172.21.0.1:18117/health`；推理为 `POST /internal/model/two-tower/user-embedding`，传入 `model_key` 与最新在前的 `history_item_ids`。返回 64 维归一化向量，词表外历史返回空向量。接口只用于内部网络。

`python -m unittest test_two_tower_runtime.py` 验证 HTTP 协议回归。`verify_two_tower_serving.py --directory <产物目录> --reference <参考代码目录> --output <报告路径>` 对照真实推理与精确检索；参考目录需要仓库的 `python_agent/rs_core/online/recall/two_tower_query.py` 和对应 `vector_index.py`。接入范围与线上证据见 [接入记录](../../../../docs/superpowers/plans/2026-09-13-two-tower-home-integration.md)。

This directory starts the local Qwen3.5-4B vLLM service and warms the prefix cache for:

- `rs_agent`
- `rag_agent`

It also contains the internal BGE-M3 embedding runtime used by the recommendation
service for semantic and RAG vector queries.

## BGE-M3 embedding runtime

The runtime loads the local BGE-M3 directory on GPU 0 and exposes only the Docker
bridge endpoint expected by `rs-service-recommend`:

```bash
cd ~/RS_agent_java/model_deploy
./start_bge_m3_embedding.sh
curl http://172.21.0.1:18115/health
```

The expected response reports `dimension: 1024`. Use
`restart_bge_m3_embedding.sh` after updating the runtime code. The remote deployment
installs `start_bge_m3_embedding.sh` as a user `@reboot` cron entry.

The warmup runs when the model service starts. A keepalive loop can then periodically replay the same prefixes so vLLM keeps the cache hot under normal traffic.

## Start

```bash
cd ~/RS_agent_java/model_deploy
cp .env.example .env
./run_qwen35_4b_vllm.sh
```

For a detached remote service, redirect the wrapper with `nohup`; its log can be
written to `vllm.log` in this directory.

The script:

1. starts vLLM with `--enable-prefix-caching`;
2. enables Qwen automatic tool parsing with `--enable-auto-tool-choice --tool-call-parser qwen3_xml`;
3. waits for `http://127.0.0.1:18082/v1/models`;
4. sends warmup requests for `rs_agent` and `rag_agent`;
5. waits `VLLM_DELAY_AFTER_WARMUP_SEC`;
6. runs the JSON Schema and strict-tool probes;
7. writes `VLLM_READY_FILE` only after all probes pass;
8. starts the optional keepalive loop.

`VLLM_ENFORCE_STRICT_TOOL_CALLING=true` is exported by default so strict tools can use
vLLM's structural-tag constrained decoding. The Qwen3.5 tokenizer bundled with the
current model uses the Qwen XML tool-call format, so the default parser is `qwen3_xml`.

## 本地 Qwen 约束解码接入（2026-10-09）

现有 Qwen3.5-4B 服务固定使用 `VLLM_STRUCTURED_OUTPUTS_BACKEND=xgrammar`，原有权重、端口与 prefix cache 保留。启动流程在预热后执行结构化输出探针，全部通过才创建 ready 文件；失败则启动脚本退出并关闭本次创建的 vLLM 子进程。默认验收报告为 `<VLLM_READY_FILE>.structured-output.json`。`VLLM_STRUCTURED_OUTPUT_PROBE=false` 可用于诊断，但这时 ready 仅表示预热完成，不能作为约束能力的验收证据。

本次核对的服务器环境为 vLLM 0.24.0、XGrammar 0.2.3、`qwen3_xml` parser。使用 `--structured-outputs-config '{"backend":"xgrammar"}'`，不向该版本传入尚不支持的 `--tool-strict-level`。每个工具必须在 `function.strict` 设置 `true`，才能按该版本的工具协议约束参数。

Java Agent 继续使用现有 `spring_ai` 通道，连接本地模型时设置：

```bash
RS_AGENT_OPENAI_BASE_URL=http://127.0.0.1:18082/v1
RS_AGENT_OPENAI_MODEL=qwen35-4b
RS_AGENT_API_KEY=local-unused
RS_AGENT_CONSTRAINED_DECODING_ENABLED=true
```

以上地址用于主机进程或既有 SSH 隧道；容器使用能够访问模型的地址，不能直接使用容器自身的 `127.0.0.1`。现有模型默认只监听主机 loopback，不能仅修改客户端地址就认定跨容器链路已接通。

本地 Java 服务可直接启用 `local-qwen` Spring profile，预设上述模型地址、模型名和约束开关；其他已启用的数据库或会话 profile 可以同时保留。自定义地址用 `RS_AGENT_LOCAL_MODEL_BASE_URL`，模型名用 `RS_AGENT_LOCAL_MODEL_NAME`。例如从 `java_agent` 目录启动：

```powershell
mvn -pl rs-service-agent spring-boot:run '-Dspring-boot.run.profiles=local-qwen'
```

该开关让实际请求包含 `tools[].function.strict=true`，关闭并行工具调用与 Qwen thinking，普通轮次使用 `required`，最终回答轮次指定 `emit_final_answer`。这是对 Spring AI 2.0.0 将 strict 放入 parameters 的协议适配；现有工具 schema 和 AgentLoop 的执行职责不变，公开响应仍通过 `PublicAgentResponseProjector`。开关默认关闭，外部模型通道不会自动使用 Qwen 专属参数。

普通 JSON 输出使用 `response_format.type=json_schema`。工具输出约束参数 schema，不为整个工具轮次叠加普通 JSON 的 response_format。探针覆盖原生 JSON、named/required/auto 的非流式与流式调用，共七种组合，重组完整参数后校验。auto 用例明确要求调用指定工具，约束本身不改变 auto 可以返回普通文本的语义。

流式验收必须同时收到成功的 finish_reason 和 `[DONE]`；`length`、内容过滤、缺少终止标记、错误事件及意外并行调用都会失败。格式合规仍不能替代商品事实与 Profile allowlist 校验。

本机验证：

```powershell
python -m pytest tests/test_vllm_constrained_startup.py tests/test_vllm_structured_output_probe.py tests/test_vllm_prefix_warmup.py -q
mvn -f java_agent/pom.xml -pl rs-service-agent -am '-Dtest=SpringAiAgentModelStreamClientSmokeTest,AgentModelProviderConfigurationTest,SpringAiAgentToolCallbackFactoryTest' '-Dsurefire.failIfNoSpecifiedTests=false' test
```

真实模型联调测试单独启用，默认测试不会访问模型或加载权重。先建立现有 SSH 模型端口隧道，然后运行：

```powershell
$env:RS_AGENT_TEST_VLLM_BASE_URL='http://127.0.0.1:18082/v1'
mvn -f java_agent/pom.xml -pl rs-service-agent -am '-Dtest=LocalVllmConstrainedDecodingSmokeTest' '-Dsurefire.failIfNoSpecifiedTests=false' test
```

该测试验证现有 Java 客户端向真实 Qwen 发起 required 与 named 工具调用，并将返回 blocks 交给现有公开投影器。2026-10-09 已通过七种 runtime 探针与两种 Java 调用；当日服务器原模型服务未启动，GPU 0/2 均有其他任务占用，因此在空闲 GPU 1 验证，并将原部署 `.env` 的设备更新为 1，原文件保存为 `.pre-constrained-20261009` 备份。源代码中的示例设备仍需按目标服务器资源配置。

## Structured-output probe

After vLLM is ready, verify both native JSON-schema output and strict tool arguments:

```bash
python3 vllm_structured_output_probe.py
```

The probe checks:

- `response_format.type=json_schema` with a strict final-answer schema;
- a named strict `emit_final_answer` tool call;
- reconstruction and validation of streaming tool argument chunks.

The same script can be checked locally without contacting a model:

```bash
python3 vllm_structured_output_probe.py --dry-run
```

## Agent configuration

Point `rs-service-agent` to the local vLLM OpenAI-compatible endpoint:

```bash
RS_AGENT_OPENAI_BASE_URL=http://host.docker.internal:18082/v1
RS_AGENT_OPENAI_MODEL=qwen35-4b
RS_AGENT_OPENAI_TEMPERATURE=0
RS_AGENT_OPENAI_MAX_TOKENS=256
```

If the Java services run on the same Linux host network instead of Docker Desktop, use the reachable host IP or add an equivalent Docker host mapping.

## Keeping the cache hot

vLLM prefix cache 位于 GPU 显存，容量不足时仍会淘汰旧块。当前模型与 BGE 共用 GPU 1；`--enable-prefix-caching`、合适的上下文与显存比例以及定时保温可以帮助复用常见前缀，不能固定缓存块或保证不发生淘汰。`VLLM_PREFIX_KEEPALIVE=true` 按 `VLLM_KEEPALIVE_INTERVAL_SEC` 重放配置的请求文件；未提供文件时才使用 `rs_agent` / `rag_agent` 的提示词预热。保温默认只在运行和等待请求均为零时尝试。

Do not mix long-context batch jobs on the same vLLM instance if low TTFT is the goal. Use another port or another GPU for long prompts, offline jobs, and experiments.

2026-10-11 的速度优先量化对照未获得稳定业务加速，曾恢复 BF16。之后按用户“腾出显存优先”的要求，正式部署保持原分词器的 INT4 AutoRound，并把 `VLLM_GPU_MEMORY_UTILIZATION` 从 0.78 降到 0.50；16K 上下文、strict 工具和启动探针保留。GPU 1 实测释放约 6.63 GiB，空闲约 9 GiB。五条真实业务均返回最终回答，其中一条 `rag_support` 失败，内部工具检查 4/5 通过。当前配置、验证与备份恢复入口见[显存优先部署记录](../../../../docs/reports/model-quantization-20261011/memory-deployment.md)，先前对照及因果限制见[量化对照记录](../../../../docs/reports/model-quantization-20261011/README.md)。

## Prompt source

For custom platform prompts, prefer one of:

```bash
AGENT_SYSTEM_PROMPT_FILE=/path/to/system_prompt.txt
AGENT_SYSTEM_PROMPT_URL=http://127.0.0.1:18104/api/platform/agent/runtime/system-prompt
```

If neither source is available, the warmup script uses a conservative fallback prompt. That still warms the runtime path, but it will not perfectly match a customized Agent prefix.

## 2026-09-05 重排能力与验收

`run_bge_m3_embedding.sh` 支持可选 `BGE_RERANKER_MODEL_PATH`，指向已存在的本地 CrossEncoder 模型目录。配置后提供 `/internal/model/rank`，未配置时返回 503。额外模型会增加内存/显存占用，部署前按项目资源限制核算。

可将 GPU、监听端口和权重路径保存在同目录的 `bge-runtime.env`，启动与重启脚本均会读取该文件，避免重启后丢失重排配置。例如：

```bash
CUDA_VISIBLE_DEVICES=2
BGE_M3_PORT=18116
BGE_RERANKER_MODEL_PATH=/home/luo/RS_agent_java/data/models/BAAI/bge-reranker-v2-m3
```

此文件是部署主机的本地配置；Java Model 的两个运行时地址必须与其实际监听地址一致。

健康接口 `capabilities` 区分 `embed` 和 `rank`。Java Model 分别设置 `RS_MODEL_RUNTIME_EMBEDDING_BASE_URL` 和 `RS_MODEL_RUNTIME_RERANK_BASE_URL`；只有该运行时启用重排后，才将后者指向相同地址。先更新运行时，再更新 Model，避免旧健康响应缺少能力字段。

重排保留输入候选 item_id（包括 RAG evidence 后缀）。本地契约测试使用替身，真实权重、GPU 资源和部署连通性仍待远程验证。模型参数依据 [CrossEncoder 官方接口](https://www.sbert.net/docs/package_reference/cross_encoder/model.html)。

## 已训练 COLD / DeepFM CPU 排序服务

`prepare_trained_ranking.py --train <原始 train.jsonl> --models <cold_model.json 与 deepfm_model.json 所在目录> --output <新目录>` 从训练正向事件建立 SQLite 特征快照；在服务器执行，不在本机加载完整训练集。输出目录必须不存在。模型和特征版本绑定在 serving-manifest.json，当前静态快照不会自动更新。

部署 `trained_ranking_runtime.py` 至 `~/RS_agent_java/model_deploy/`，将 `rs-trained-ranking-runtime.service` 放入 `~/.config/systemd/user/`，执行 `systemctl --user daemon-reload` 和 `systemctl --user enable --now rs-trained-ranking-runtime`。默认端口 18119，`GET /health` 查询模型哈希及版本；`POST /internal/ranking/cold-deepfm` 提供 chain/coarse/fine 三个阶段。服务只允许内网调用。

`verify_trained_ranking.py --directory <模型特征目录> --reference <原 ltr.py / cold_deepfm.py 目录> --output <报告.json>` 独立重扫 train 并比较原函数与在线分数。当前验证工具使用固定的 172.21.0.1:18119 地址。恢复完整步骤与限制见 [排序接入记录](../../../../docs/superpowers/2026-09-13-trained-ranking-serving.md)。
