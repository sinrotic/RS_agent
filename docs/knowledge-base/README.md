---
id: kb-index
type: index
status: current
owner: project-maintainers
last_verified: 2026-09-05
confidence: confirmed
---

# RS Agent 核心知识库

服务可靠性最新变更与部署验收边界见 [2026-09-05 修复记录](../superpowers/plans/2026-09-05-service-reliability-repairs.md)。该记录对应本地代码，远程发布尚待验收。

本目录是后续迭代开发的统一入口，用来回答“系统当前是什么、哪些边界不能破坏、修改后如何验证”。它不复制代码、ADR、运行手册或实验报告，而是说明这些事实在哪里，并补齐跨模块视角。

## 阅读入口

| 主题 | 文档 | 解决的问题 |
| --- | --- | --- |
| 项目全景 | [项目概览与当前状态](project-overview.md) | 项目目标、技术主线、能力成熟度和已知冲突 |
| 领域语言 | [领域模型与核心不变量](domain-and-invariants.md) | 应使用哪些术语，哪些系统行为不能被普通迭代破坏 |
| 模块边界 | [系统架构](architecture.md) | Java、Python、前端、模型和基础设施如何协作 |
| 接口协作 | [接口与数据契约](contracts.md) | 外部、内部、Agent、平台接口及 Schema 权威来源 |
| 数据责任 | [数据流与事实来源](data-flow.md) | 数据从哪里来、存在哪里、谁是权威、什么可重建 |
| 开发验证 | [开发、测试与部署指南](development-guide.md) | 环境、命令、测试矩阵、部署入口和资源限制 |

领域术语的最终定义位于仓库根目录的 [CONTEXT.md](../../CONTEXT.md)，架构取舍的最终依据位于 [docs/adr](../adr/)。

## 事实可信度顺序

当资料发生冲突时，按以下顺序判断，但不得静默忽略冲突：

1. 当前代码、配置、数据库 Schema 和可执行测试，说明系统“实际做什么”。
2. `CONTEXT.md` 规定领域词汇；已接受的 ADR 规定不可随意改变的架构决策。
3. Python 的 [Current Route Registry](../../python_agent/configs/governance/current_route_registry.yaml) 规定受治理的当前路由和晋级边界。
4. 本知识库汇总跨模块事实，并显式记录仍未解决的不一致。
5. `docs/superpowers/plans`、`docs/superpowers/specs`、`docs/research` 和 Python `dic/` 中带有规划或实验语义的文档只能证明意图或历史，不能单独证明能力已经上线。
6. `outputs/`、`old_dic/`、构建目录和缓存目录不是当前设计的权威来源，除非被 registry、ADR 或正式验收记录明确引用。

若代码与 ADR 冲突，应停止把冲突行为描述为正式能力，并在 Issue 中决定修代码还是重开 ADR。

## 状态词汇

| 状态 | 含义 |
| --- | --- |
| `current` | 当前默认路径或已接受事实，仍需通过对应测试证明可运行 |
| `provisional_current` | 当前演示或试运行入口，尚未获得生产级承诺 |
| `experimental` | 只允许实验、诊断或受控验证，不得自动晋级主路 |
| `planned` | 已有设计或计划，但不能据此声称实现完成 |
| `deprecated` | 已退役或只为兼容保留，不得成为新开发默认入口 |
| `unknown` | 现有证据互相冲突或不足，需要 Issue 澄清 |

## 维护规则

以下变化必须在同一个 PR 或变更集中更新知识库：

- 新增、删除或重命名 Java 服务、Python canonical 模块、网关路由或部署 profile。
- 修改公开 API、内部 API、事件、SSE、认证身份头或公开展示 Schema。
- 改变数据库事实来源、缓存策略、Schema 版本、迁移顺序或数据保留方式。
- 修改推荐主路、实验晋级门禁、模型 Artifact 或 `rs_core`/`rs_lab` 边界。
- 修改本地开发、CI、smoke、部署命令或资源限制。
- 接受、替代或废弃 ADR。

每次更新至少同步 `last_verified`，并保留可检查的源码、配置、测试、Issue 或 ADR 链接。知识库只描述可验证事实；推断必须标为推断，冲突必须进入“待澄清事项”。

## 文档完成标准

一项知识库更新只有同时满足以下条件才算完成：

- 使用 [CONTEXT.md](../../CONTEXT.md) 中的规范术语。
- 没有把规划、实验或 smoke 结果写成正式上线能力。
- 每项关键事实都能追溯到代码、配置、Schema、测试、ADR 或 Issue。
- 相对链接可从当前文件解析。
- 与 [项目规则](../../CLAUDE.md) 的中文输出和 12GB/14GB 本地资源限制一致。
