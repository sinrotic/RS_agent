# 文档路由规范

本文档说明新增项目文档应该放到哪里，避免继续把阶段报告、实验报告和规范文档堆在 `dic/` 根目录。

## 1. 总原则

- `dic/` 根目录只保留项目文档入口和高频维护文档。
- 架构、阶段、实验、规范、决策类文档进入对应子目录。
- `old_dic/` 只保存历史草稿，不作为当前模型路线、Agent 规划或阶段计划依据。
- `.omc/` 是 OMC 工作流状态和交接产物，不纳入项目正式文档体系。
- 说明文档、过程日志、复盘材料和报告草稿默认使用中文。

## 2. `dic/` 根目录保留范围

根目录只建议保留：

- `README.md`：文档入口和主阅读路径。
- `PROJECT_STRUCTURE.md`：项目目录职责和演进边界。
- `ENGINEERING_NARRATIVE_LOG.md`：面试导向工程叙事日志。
- `OPTIMIZATION_NARRATIVE.md`：排序/召回/效果优化叙事。

普通实验报告、阶段中间结论、一次性草稿不再新增到根目录。

## 3. 新增文档放置规则

| 文档类型 | 推荐目录 | 说明 |
|---|---|---|
| 架构设计、模块边界、长期路线 | `dic/architecture/` | 包括 Agent 架构、推荐主链路、服务/前端/仿真边界 |
| 阶段计划、阶段复盘 | `dic/phases/<phase>/` | 例如 `dic/phases/phase_1_5/` |
| 技术决策、ADR | `dic/decisions/` | 记录不可逆或影响路线的决策 |
| 排序实验报告 | `dic/experiments/ranking/` | 包括排序权重、LTR、pool200、ranking pipeline 等 |
| 召回实验报告 | `dic/experiments/recall/` | 包括 item graph、two tower seed、召回健康度等 |
| demo / hybrid demo 报告 | `dic/experiments/hybrid_demo/` | 包括 hybrid demo、小样本 demo、LOPO demo |
| 消融实验报告 | `dic/experiments/ablation/` | 包括 no_category、no_semantic、no_popular 等 |
| 工程规范 | `dic/standards/` | 包括测试、CI、代码组织、实验产物规则 |
| 文档/产物/配置路由说明 | `dic/guides/` | 包括本文档、outputs 规则、configs 规则 |
| 历史证据和旧材料 | `dic/archive/` | 只作历史参考，不作为当前主入口 |

## 4. 命名规则

- 旧文件迁移时优先保留原文件名，只改变目录，降低断链风险。
- 新增阶段文档文件名包含阶段号，例如 `PHASE_1_17_*.md`。
- 新增实验文档文件名包含实验对象、数据范围或候选池信息。
- 新增 ADR 文件名建议包含阶段号和决策主题，例如 `PHASE_1_31_FINAL_OFFLINE_RANKING_ROUTE_ADR.md`。

## 5. 迁移硬约束

- 不做一次性大规模迁移。
- 每批只移动一组强相关文档。
- 每批迁移后检查 `git diff`、路径引用、Markdown 链接和入口文档可读性。
- 发现断链、脚本硬编码路径或实验复现路径不确定时，先修复再继续。
