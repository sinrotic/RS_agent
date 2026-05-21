# pool500 召回治理

## artifact 边界

pool500 召回实验区允许保存诊断 sidecar、source manifest、readiness contract 和 resource audit，但这些产物必须保持诊断语义，不能直接冒充正式召回产物。

## 当前 gate 约束

- `ranking_input_replacement_allowed=false`
- `pool1000_allowed=false`
- `diagnostic_sources_must_not_replace_ranking_input=true`
- 重任务必须使用 guarded process 或等价资源控制。

## source 晋升要求

source 进入正式 pool500 主路前至少需要满足：

1. source readiness 为 `READY`。
2. target batch 不再系统性 underfill。
3. source manifest 字段稳定，能通过 focused tests。
4. route gate 没有 source readiness blocker。
5. 资源使用在可接受范围内并有审计记录。

## fallback completion contract

`fallback_completion_contract.py` 只定义 pool500 fallback 补齐的预晋升治理契约，用于审计低历史用户从个性化候选不足到补齐 500 的过程。它不是正式主路 runner，也不能声明 `FULL_POOL500_READY`。

合约要求：

- 用户按 `ZERO_HISTORY`、`ZERO_POSITIVE_HISTORY`、`LOW_HISTORY_SINGLE_SEED`、`LOW_HISTORY_MULTI_SEED`、`NORMAL_HISTORY` 分层。
- 补齐来源按个性化主路、种子类目 sibling、种子 metadata neighbor、种子 semantic token、类目热门、上下文热门、全局多样性热门的顺序审计。
- 所有晋升相关 flag 固定为 false，包括候选生成、排序输入替换、排序替换、promotion、pool1000 和 full pool500 ready 声明。
- 审计必须记录每个用户的补齐比例、热门比例、来源构成、风险等级、重复 item 与是否超过 target；全局审计必须汇总 underfill、风险用户数和来源贡献。

该合约当前只提供证据边界：即使全局热门可以把零历史用户补齐到 500，也必须保留高风险标记，不能据此对外宣称 pool500 已完成晋升。

## 当前判断

UserCF / ItemCF 已完成 target500 诊断接入，但仍是 `DIAGNOSTIC_ONLY`。semantic / co_visit / two_tower 仍缺少可用 full-clean-safe artifact，保持 `DEFERRED`。
