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

## 当前判断

UserCF / ItemCF 已完成 target500 诊断接入，但仍是 `DIAGNOSTIC_ONLY`。semantic / co_visit / two_tower 仍缺少可用 full-clean-safe artifact，保持 `DEFERRED`。
