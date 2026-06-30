# 代码库治理指南

本文档定义当前阶段的轻量治理框架，目标是让后续开发 Agent、召回、排序和展示链路时，能明确当前主路、实验晋升方式和历史产物边界。

## 1. Current Route Registry 使用方式

当前权威主路登记在 `configs/governance/current_route_registry.yaml`。它不是全量实验资产目录，只记录后续开发最容易误用的默认入口：

- `current_recall_route`：当前召回主路。
- `current_ranking_route`：当前排序主路。
- `current_agent_demo_route`：当前 Agent / serving demo 默认入口。
- `pool500_recall_continuation_route`：pool500 recall-only 延续路线。

普通探索脚本不需要先登记 registry；只有实验要晋升为当前主路、稳定 workflow 或 Agent 默认入口时，才必须更新 registry 并通过对应门禁。

Registry 路径统一使用 repo-relative path。current route 不应指向 `old_dic/`，也不应指向一次性 smoke、verifier、batch tuning 产物作为权威证据。

## 2. recall route promotion

召回实验晋升为当前召回路线前，必须满足：

- source set、candidate pool size 和数据范围明确。
- 不使用 holdout / valid / test 作为候选生成输入。
- 不引入 pool1000 产物。
- 不替换 ranking input。
- 有 route gate、质量审计或等价证据。
- 有测试或 smoke 验证。
- registry 中登记 config、workflow/script 和必要 manifest。

pool500 当前只能作为 recall candidate / recall continuation。除非后续单独通过排序晋升门禁，否则不得把 pool500 recall-only 产物登记为 `current_ranking_route` 的输入。

`pool500_recall_continuation_route` 使用 v5 artifact gate 语义，合法决策只允许：`FULL_POOL500_READY`、`DIAGNOSTIC_ONLY_PARTIAL`、`STOP`。其中 `FULL_POOL500_READY` 只表示 pool500 recall artifact ready，不表示可以替换 ranking input；legacy / precheck / dry-run 产物不得标记为 full-ready。该 route 不授权候选生成、不接 ranking、不替换 `current_ranking_route`。

## 3. ranking route promotion

排序实验晋升为当前排序路线前，必须满足：

- 输入候选池来源明确，不能静默切换 recall baseline。
- 排序指标、case、manifest 或等价产物可复现。
- 明确 top-k、candidate pool、rerank/LTR/feature 开关。
- 有 ranking 测试或 smoke 验证。
- 有 ADR、实验报告或优化叙事说明为什么晋升。
- registry 中登记当前 config、workflow/script 和权威证据。

如果排序实验依赖新的 recall output，必须先确认该 recall output 已通过 recall route promotion，且不会绕过 ranking input replacement gate。

## 4. Agent demo route promotion

Agent demo / serving 默认入口晋升前，必须满足：

- 指定 demo config。
- 指定 serving 或 evaluation script。
- 明确依赖哪个 recall route 和 ranking route。
- 展示层 contract 清楚，不直接依赖推荐内部临时字段。
- Agent runtime 不直接嵌入治理细节。

后续可以增加轻量 route resolver 读取 registry，为 serving 或 Agent demo 提供默认 config；但 `rs_core/agent/runtime/__init__.py` 应继续聚焦对话 loop、状态和诊断，不承载 registry schema、CI allowlist 或 phase 判断。旧 `rs_core/rsagent` active package 已删除，新增 Agent runtime 能力必须进入 canonical `rs_core/agent/*`。

## 5. stable workflow promotion

实验 workflow 晋升到 `rs_core/workflow/**` 前，必须满足：

- 不硬编码 phase、p7、batch、固定 outputs 路径。
- 阶段信息、配置路径和输出路径通过参数或 config 注入。
- CLI wrapper 保持薄入口，只做参数解析和流程触发。
- 有对应测试。
- 如果保留旧入口，应说明 wrapper 或 deprecated 关系。

历史遗留的阶段性硬编码第一轮可以进入 warning allowlist，但新增稳定 workflow 不应继续引入同类硬编码。

## 6. outputs 生命周期

`outputs/` 只保存运行产物，不保存长期说明文档或架构决策。

长期保留的 outputs 应满足至少一个条件：

- 被 registry 引用为当前主路证据。
- 被阶段文档、实验报告或 ADR 明确引用。
- 是可复现实验所需 artifact。

一次性 smoke、verifier、debug、batch tuning 产物在结论沉淀后应清理或进入 follow-up 清单。第一轮治理不直接删除 outputs，只记录风险和后续处理建议。

## 7. warning allowlist 生命周期

治理检查的 warning allowlist 位于 `configs/governance/engineering_contract_allowlist.yaml`。

每条 allowlist 必须包含：

- `check`
- `path`
- `reason`
- `owner`
- `created_at`
- `review_after`

warning-first 是为了避免历史遗留让 CI 一次性全红，不是永久豁免。新增问题默认不得自动进入 allowlist；过期项应在后续治理中复查。

## 8. team+ralph 执行规则

使用 team+ralph 执行治理时，按以下顺序推进：

1. 只读扫描 current route 候选。
2. 创建或更新最小 Current Route Registry。
3. 更新晋升门禁文档。
4. 扩展工程契约和测试。
5. 只对高风险混杂点做小步治理。
6. 使用项目 `.venv` 运行验证。

明确不做：

- 不做全仓库目录重排。
- 不一次性删除历史 phase 脚本。
- 不一次性清空 outputs。
- 不把 `old_dic/` 重新纳入当前规划依据。
- 不把 pool500 recall-only continuation 当成 ranking input。

第一轮完成标准是 registry 可解析、路径存在、promotion gate 文档化、工程契约测试通过、pool500 recall-only 边界未被破坏。历史清理项进入 follow-up，不阻塞本轮完成。
