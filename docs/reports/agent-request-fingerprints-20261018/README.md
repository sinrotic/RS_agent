# 模型请求指纹与评测关联

日期：2026-10-18。基于 `301b4579`，将请求组装处的配置与输入摘要绑定到真实模型调用，补充 P1 的版本观测。指纹可以定位两次调用的输入或配置差异；历史输入与不可变配置资产仍需单独保存，不能仅凭哈希还原一次实验。

## 调用接入

`AgentLoop → 模型许可 → AgentModelCallObservation → Adapter 组装请求 → 指纹回调 → model_call_completed → 平台原始事件 / Python 账本 / OTLP 白名单`。

`AgentModelStreamClient` 新增带独立观测回调的兼容重载；旧 Adapter 继续运行，其版本标记为 `not_reported`。观测不借用 token/tool/done 事件，不新增公开 SSE 类型。只有完成事件承载本次版本摘要，继续沿用同一 `model_call_id`、Turn 和 loop 标识。

指纹计算与接收异常不会替换模型异常或改变取消行为。重复一致的摘要允许接收；同次调用收到不一致摘要时保留 `conflict`，不能由后来的值覆盖成可信版本。完成后不接受改写。版本不完整与 usage 不完整分别计量，不用版本缺失伪造 token 为零，也不因观测失败直接判定推荐失败。

## 字段与范围

契约版本为 `rs-agent-model-request-fingerprint/1`。哈希采用规范化 JSON 的 SHA-256：Map 键排序，List 顺序与字符串内容保留。摘要流式写入哈希器，不再为完整请求复制一份 JSON 字节数组。

| 字段 | 观测范围 |
| --- | --- |
| `prompt_sha256` | 已配置的基础系统提示词、Adapter 字节码指纹及当前请求的运行规则；普通用户问题和商品结果不参与。条件分支另由请求选项与实际请求摘要区分 |
| `tools_sha256` | Spring AI 严格模式使用实际生成并传入请求的严格工具定义，包含精简后的 Schema；普通模式使用 callback 名称、说明及 schema 字符串；HTTP Adapter 只记录转发的工具上下文 |
| `skills_sha256` | 请求中的 Skill 目录视图、服务端加载视图及成功 `load_skill` 的声明内容；尚未加载的 Skill 正文不在范围内，外置内容引用也不等于完整正文 |
| `request_options_sha256` | 显式模式与预算配置，以及可读取的生成默认值白名单；不包含鉴权、地址、请求头、用户标识或任意 extra body |
| `adapter_sha256` | 正在执行的 Adapter class 文件，可与本批编译产物指纹对照；它不是远端模型版本 |
| `declared_model_sha256` | 能读取时记录配置模型名的摘要，`model_identity_status=configured_alias`；仅有 ChatClient 或 Python 远端接口时可能未知 |
| `request_sha256` | Spring AI 已组装的 system/user 文本、工具及上述选项，或 HTTP Adapter 的完整逻辑 payload；它是规范化逻辑摘要，不是 HTTP 原始字节校验和 |

生成参数白名单涵盖 model、temperature、max tokens、top-p/top-k、stop，以及 OpenAI 的 max completion tokens、seed、频率/存在惩罚、reasoning effort、verbosity、response format、logit bias 和 n。仅接收 ChatClient 时无法读取其完整默认值；SDK 后续合并、Advisor 或远端模板处理也不属于本次快照，不能称为完整网络请求审计。

`fingerprint_scope` 明确区分 `spring_ai_prepared_request`、`self_hosted_adapter_request` 和 `python_agent_adapter_request`。后两者只能证明 Java 转发了什么，不能证明下游最终使用了什么 Prompt 或权重。模型名也不能证明模型文件、LoRA、索引或数据快照版本。

## 外发与恢复规则

`request_sha256` 涉及用户输入，只进入内部调用观测与离线账本，明确排除在 OTLP 白名单之外。外发只补充合法配置哈希、允许的 scope/status，不发送 Prompt、Skill 正文、工具参数或请求头。配置哈希用于关联，不替代访问控制，也不承诺匿名化。

本批不将 Prompt、Schema、Skill 或指纹回注模型上下文、Session Event 或 Context Checkpoint；恢复仍按 [ADR 0002](../../adr/0002-context-checkpoint-excludes-runtime-injection.md) 使用当前运行配置。本批没有引入旧版本选择、权限固化或自动回滚。

Python 每条 trial 的 `model_usage` 新增 `request_fingerprints` 与 `fingerprint_coverage`，按调用保留摘要，分别统计已观测调用、状态和各字段覆盖数。缺失、非法和冲突保持显式；同一完成事件的重复导出不会增加分母，互相冲突的完成记录仍拒绝汇总。

## 验收

机器可读结果与源文件/编译产物指纹见 [checks.json](checks.json) 和 [manifest.json](manifest.json)。

- JDK21 Agent 及上游打包：263 项收集，262 通过，1 项既有本地 vLLM smoke 跳过。
- 真实 Spring AI 自动配置、OpenAI-compatible HTTP 与 Agent Loop 联调：三组精简/自定义 Loop 场景中，每次调用的工具指纹都与实际发出的工具定义一致。HTTP 返回受控工具响应，不作为真实模型效果证据。
- 行为回归覆盖用户问题变化、Prompt 和工具说明修改、已加载 Skill 内容变化、最终回答模式、模型别名未知、两个 HTTP Adapter 的 payload、Map 排序与 List 顺序、失败隔离、去重与冲突、关闭后不可改写，以及实际请求摘要不外发。
- Python CI 的 unit/smoke/serving 标记选择共 125 个文件：1269 通过、5 跳过；最终账本字段另经 Java/Python 联调与评测测试 42 项复核，全部通过。Ruff 全 CI 范围通过。
- 根部署/启动契约 56 项通过。前端和平台服务本批没有修改，未重复运行其测试。

当前 `SkillBenchmarkMain` 使用自己声明的评测 JSON Adapter，尚未实现新回调，因此 Java/Python 联调报告中的逐次指纹保持 `not_reported`；不能把它原有的全局 runtime 指纹冒充生产 Spring AI 请求指纹。生产请求路径由上述真实 Spring AI HTTP 测试验证。

## 后续验收

P1 仍需接通跨 HTTP 委派父子标识、摘要/Judge 等调用种类、完整数据与权重来源、导出指标注册和真实远端接收。Prompt 不可变资产、历史重放与实验版本选择继续属于 P7；现有摘要不会提前把这些工作标为完成。

没有加载正式模型、训练或远程部署。此前 SSH 目标不可达，本批沿用本地验收范围。既有工程规范问题仍按 [基线记录](../agent-capability-baseline-20261018/README.md) 跟踪，不能将本批测试通过解释为整个 CI 已无存量问题。
