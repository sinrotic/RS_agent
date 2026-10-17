# 个人推荐 Agent 固定验收集 v1

对应 [JSON 快照](agent-baseline-v1.json)。6 个合成商品、3 个完整任务、9 次推荐；Java 验收每个任务独立重复两遍。没有调用正式模型、访问真实用户数据或加载大模型。

Java 测试使用真实 Controller、预算过滤、最终候选处理、Recommendation Delivery、反馈事件、在线偏好和撤回逻辑。Catalog、Recall Source、身份校验及持久化存储使用测试 Adapter，不能据此宣称真实数据库恢复、模型理解或线上满意度已验收。查询与预算参数由夹具分别给出，所以也不验证从自然语言提取预算的能力。

## 固定场景与拆分

| family / split | 三轮行为 | 验收重点 |
| --- | --- | --- |
| budget-change / train | 50 元 → 15 元 → 9 元 | 当前预算覆盖旧预算；未知价格不能过预算；无匹配时返回空候选 |
| dislike-recommend / dev | 推荐 → 不喜欢换推荐 → 继续缩预算 | 反馈在线生效；被排除商品不复活；允许真实供给不足 |
| feedback-reversal / test | 推荐 → 不喜欢 → 撤回 | 撤回是新事件；恢复有效候选；重复提交不增加版本 |

每个 family 使用不同的合成 Account、Profile User、Session。完整 family 不跨 split。商品目录共享，因此这些 split 仅用于工程契约覆盖，不构成训练后泛化的独立留出证据，也不能拿 test 调参后宣称独立测试。后续训练需使用独立的数据 manifest 和拆分。

`before`、`constraints`、`expected_item_ids` 和 `trusted_identity` 是 Java API 契约执行器的夹具扩展。`before` 由测试先提交真实反馈接口；通用 Skill 评测运行器不会执行这些扩展，因此不能用通用运行器的得分替代本契约验收。Gold 和 expected 列表都不传给模型。

## 指标口径 v1

执行口径由 [execution_metrics.py](../../rs_core/offline/evaluation/skill_benchmark/execution_metrics.py) 提供。后续观测与实验阶段负责把完整调用事件接入，当前 Java API 报告不伪造 Agent 完成率或模型 usage。

- Turn 分母为计划执行的全部 Turn。缺失、中断、失败均保留；同一 Session/Turn 重复记录拒绝接受。
- `FINAL_ANSWER`、`INTERRUPTED`、`HOOK_STOPPED`、`MAX_LOOP`、`MODEL_ERROR`、`TOOL_ERROR` 是终态；`NEXT_TURN` 仅为内部循环转移。
- 任务完成必须同时满足最终回答、独立业务完成检查以及硬约束通过或不适用。HTTP 200、工具返回成功、仅有文本不能代替完成；unknown 不能当 pass。
- 延迟区分完整 Turn 与首 token；缺失保持缺失，报告实际观察数量，不用 0 填补。API 夹具的执行耗时不作为模型服务性能。
- 每次真实模型尝试分配唯一 `model_call_id`；生成、重试、摘要、Judge 均需登记。相同最终快照重复导出只记一次；同一 ID 的冲突快照拒绝相加，流式累计快照需先归一。
- 逐字段报告 usage 总量、已知小计和覆盖率。存在缺失时总量为 null；缓存读写分别计数，不把缓存 token 再加到普通 token 总量。没有价格合同不估算费用。
- 排序指标、格式遵循和推荐满意度分别报告。本工程夹具不产生满意度分，不用于证明 32% token 降幅或训练增益。

## 重跑

先使用 JDK 21；从仓库根目录运行：

```text
mvn -B -f java_agent/pom.xml -pl rs-service-recommend -am -Dtest=FrozenAgentBaselineTest -Dsurefire.failIfNoSpecifiedTests=false test
python -m pytest python_agent/tests/test_agent_execution_metrics.py -q
python python_agent/scripts/evaluation/agent_baseline_manifest.py --output docs/reports/agent-capability-baseline-20261018/manifest.json
```

Python 命令使用已安装项目的环境。Java 原始步骤输出在 `java_agent/rs-service-recommend/target/agent-baseline/`。跨语言评测需先完成 `rs-service-agent` 的 `package`，不能在 Java 编译期间读取并计算类指纹。
