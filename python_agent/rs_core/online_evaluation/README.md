# 真实购物请求的在线评价与候选 Skill 改进

本模块在 Java Agent 完成并持久化 Turn 后接收只读旁路记录。独立 worker 提取需求、查询 Catalog、评分和汇总失败，生成候选指令 overlay 与待审核案例。推荐主路、在线偏好和已发布 Skill 保持不变；所有产物均为 `auto_deploy=false`。

## 评价链路

`Java 已完成 Turn → 异步 outbox → 鉴权接收与 SQLite 入队 → worker → 分层评价 → 候选草案和案例审核 → 现有离线 runner`

Java 请求完成钩子不调用评价模型。异步发送队列最多保留 32 个任务，落盘 outbox 最多 1000 个文件；接收失败保留文件并每 10 秒重试。队列溢出、落盘异常和接收异常有计数，可通过 observer 的 `diagnostics()` 读取。入队前进程崩溃或队列溢出可能遗漏旁路记录，不能声称全量无损；补录必须来自 Durable Session History，不能从模型自报 trace 重建商品来源。

SQLite 接收按 Session 和 Turn 幂等，内容冲突会拒绝。worker 使用 180 秒租约，失败间隔 30 秒重试，最多三次；失败后通过管理接口显式重试。评价失败的分数为未知，不是顾客任务零分。多个接收进程和 worker 必须共享同一数据库文件、身份 salt 及配置；此实现用于单机旁路，不作为多主分布式队列。

## 需求和分数的解释

需求模型仅收到截至本轮的顾客消息，不收到本轮推荐答案、候选商品或 Agent 自报需求。每个条件保留消息下标和原话引用。程序校验引用存在、字段、操作和数值范围；引用存在不能证明语义正确，因此模型需求仍为 `provisional`，不是 gold。

未配置评价模型时使用有限规则模式，只覆盖部分预算、笔尖和明确款数；其他需求保留为未评分文本。后续预算覆盖前值，明确取消预算会解除旧约束，未知币种不能直接与目录价格比较。

| 输出 | 含义 |
| --- | --- |
| `hard_gate` | 已检查条件中有失败、存在未知、全部满足，或不适用 |
| `constraint_score` | 已知条件的满足比例；必须同时查看门槛和覆盖率，不是总质量分 |
| `constraint_coverage` | 当前商品条件中可以核实的比例；缺属性和未知币种不自动通过 |
| 语义评审四维分 | 需求理解、澄清、事实依据、画像使用；0/1/2 映射 0/50/100，未知为 null |
| `overall_score`、`ndcg`、`satisfaction` | 当前均为 null；部分候选事实不能支持全目录排序或真实满意度结论 |

语义评审必须给出可核对的原话引用，当前标记为未校准代理，不用于晋级。Java 捕获暂未接入可信长期画像摘要，因此画像使用维度为未知；接口可接受明确绑定及权限校验后的摘要，不能传入任意 Agent context。后续接入画像存储时仍需独立校准。

Catalog 从 `/internal/catalog/context/item-embedding-texts` 独立获取事实，并复用既有评测的有限类目修正和标题属性提取。查询只覆盖工具见过及已展示商品，不证明完整目录不存在合格商品。价格是查询时的事实，不是交付瞬间的历史价格证明；相关失败须审核时间差后再用于改进。

## 失败归因和候选触发

报告区分明确条件违规、工具未见商品、重复商品、款数差异、未完成 Turn、工具异常和语义问题。款数不足不能在缺少完整供给目录时直接认定错误。语义问题只是待确认假设。

条件违规会附带工具已经见过的合格替代品：有替代品时优先排查选择或排序；没有时保留召回、选择和事实缺失等可能性。这不是已经证明 Skill 指令导致失败。

七天窗口内，同一 Skill、推荐模型、评价模型和评分器指纹下，同类可核对问题在至少三个不同 Session、至少两个 Profile User 中出现，会生成候选指令草案。上下文截断、未知版本、运行失败或工具异常的案例不参与全局 Skill 触发；语义代理低分也不直接触发。单个用户的偏好变化不等于全局 Skill 缺陷。

候选草案使用受控改进模板，避免把顾客原话中的指令直接写入 Skill。进入下一阶段前仍须完成归因审核、需求审核、原基准回归、新案例留出验证、评分校准和人工发布。当前没有部署或替换线上 Skill 的代码路径。

## 本地配置和启动

Python 评价模块需要以下环境变量。接收器和 worker 使用相同配置。

| 变量 | 用途 |
| --- | --- |
| `RS_EVAL_DB` | 新的本地 SQLite 队列路径 |
| `RS_EVAL_IDENTITY_SALT` | 至少 16 字符的稳定身份脱敏 salt，存入密钥配置 |
| `RS_EVAL_INGEST_TOKEN` | 内部管理和接收专用 token，未配置时拒绝接收 |
| `RS_EVAL_CATALOG_BASE_URL` | 可信 Catalog 地址，不由顾客或 Agent 提供 |
| `RS_EVAL_CATALOG_CURRENCY` | 经来源确认的目录币种；不确定则留空，预算比较保持未知 |
| `RS_EVAL_CATALOG_TOKEN` | Catalog 需要认证时的专用凭证 |
| `RS_EVAL_MODEL_BASE_URL`、`RS_EVAL_MODEL`、`RS_EVAL_MODEL_API_KEY` | 独立评价模型配置，不继承推荐模型凭证 |
| `RS_EVAL_ALLOW_LOCAL_MODEL_HTTP` | 仅本地模型测试时设为 `true`，其他模型地址使用 HTTPS |

在 `python_agent` 下启动接收器和执行有界 worker：

```powershell
python -m uvicorn rs_core.online_evaluation.app:app --host 127.0.0.1 --port 18109
python scripts/evaluation/online_evaluation.py work --limit 10
```

worker 需要由外部调度器定期执行；接收器不在顾客请求中运行模型。没有配置或开启任何自动化任务。部署时以内部网络访问接收器，使用 TLS 或受控服务网络，不把管理接口开放到公网。

Java 端配置 `RS_AGENT_ONLINE_EVALUATION_ENABLED=true`、`RS_EVAL_INGEST_BASE_URL`、相同接收 token、独占持久 outbox 目录 `RS_EVAL_JAVA_OUTBOX`，以及真实版本标识 `RS_EVAL_BASELINE_SKILL_VERSION`、`RS_EVAL_RECOMMENDATION_MODEL_VERSION`。默认开关关闭，不改变现有线上行为。版本标识是运营配置，不等于已验证的 Skill 内容哈希，晋级前需要另行核对。

## 审核案例和现有基准衔接

```powershell
python scripts/evaluation/online_evaluation.py review-pack --out online-review.json
python scripts/evaluation/online_evaluation.py improvement-jobs --baseline benchmarks/skill_benchmark/v6/benchmark.json --out candidate-jobs.json
python scripts/evaluation/online_evaluation.py reviewed-replays --review reviewed-online.json --baseline benchmarks/skill_benchmark/v6/benchmark.json --out-dir reviewed-replays
```

审核包包含成功与失败记录，不只筛选坏样本。审核人须填写 `approved`、`reviewer_id`、`export_permission` 和独立 `gold`；默认均未批准。`split` 默认 train，同一审核包内同一画像用户禁止跨集合。跨导出批次及原基准的身份重叠仍需维护独立留出登记，不能仅靠一次导出验证无泄漏。

每条获准案例生成一个现有 `rs-skill-benchmark/1` 格式的补充题集，独立保存商品快照，原 v6 文件保持不变。补充题集可用原 `skill_benchmark.py run/compare` 运行，但仍要求与其哈希绑定的评分校准收据；其目录范围是受限回放，不声称线上全目录最优。当前导出不携带长期画像，个性化评测继续使用既有画像对照基准。

候选任务包含独立 overlay 草案、基线题集哈希和验证门槛；这是等待审核和离线应用的改进任务，不是完整自动优化器。先确认归因，再由优化环节生成候选版本，并分别跑原基准及新案例留出集。不得用编写候选时看过的案例充当未见测试。

## 管理和数据保护

内部接口均要求 `Authorization: Bearer <RS_EVAL_INGEST_TOKEN>`。支持接收 Turn、读取报告、查看候选、附加反馈，以及对 failed 评价执行 retry；`GET /internal/evaluation/status` 提供队列状态数量和模型配置状态。反馈须关联本次交付中的商品并以事件 ID 幂等；点击、解释请求、喜欢或不喜欢都不直接转换成 Skill 满意度或因果标签。该接口是生产 Recommendation Feedback Event 的旁路导入入口，不替代 ADR 0017 的权威反馈存储；当前未自动接通前端反馈事件流。

接收层将 Session 和 Profile User 标识 HMAC 化，最小化字段，并遮盖常见邮箱、手机号和凭证形式。Java outbox 仍含内部不透明身份和已遮盖对话，必须限制目录访问；规则脱敏不是完备匿名化。实际启用前需确认对话使用范围、模型提供方、访问控制和留存清理策略，导出仍须人工检查敏感信息并明确授权。

本地验证覆盖真实 Java 完成钩子、Java 到 Python 的 HTTP 接收与持久队列、独立模型输入、Catalog 查询、三值检查、异常重试、反馈幂等、候选门禁及人工 gold 导出。联通验证使用受控模型与商品夹具，不代表真实推荐质量或在线满意度已经提升。
