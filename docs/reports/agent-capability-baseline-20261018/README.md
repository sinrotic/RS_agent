# 个人推荐 Agent 本地开发基线与首批实现

日期：2026-10-18。开发分支：`feat/agent-capability-completion-20261018`。初始快照 `c5d5b597`，计划起点 `453d3fc4`。

## 本轮交付

1. 固定 [验收集与指标口径](../../../python_agent/benchmarks/skill_benchmark/agent-baseline-v1.md)：6 个合成商品、3 个任务 family、9 轮推荐；预算修改、不喜欢、撤回、幂等、跨账号拒绝均可重跑。
2. [Java API 验收](../../../java_agent/rs-service-recommend/src/test/java/com/sinrotic/rs/recommend/service/FrozenAgentBaselineTest.java)：每个完整任务独立重复两次，另加跨账号用例，7 项通过。每次实际请求与响应输出至 `target/agent-baseline/`。
3. [执行指标计算](../../../python_agent/rs_core/offline/evaluation/skill_benchmark/execution_metrics.py)：计划 Turn 分母、完成条件、终态、缺失延迟、模型调用去重及 usage 字段覆盖率。7 项行为测试通过；**尚未接入全部生产调用事件**，不能把它当作已经上线的总费用账本。
4. 修正生产 Java 用量映射：SDK 未提供的缓存 token 字段不再补 0；明确返回的缓存 0 保留；部分计数不补齐未知字段；SDK 的默认空计数不生成伪 usage。
5. 为既有 `test_skill_benchmark.py` 和 `test_online_evaluation.py` 增加文件级分类，使 CI 选择器真正选中它们；修复一个未使用导入。
6. 新增 [manifest](manifest.json) 与 [生成脚本](../../../python_agent/scripts/evaluation/agent_baseline_manifest.py)，冻结关键配置、6 个 Skill、候选模型报告和验收代码的 SHA-256。只读取版本化示例及允许的非敏感字段，不读取本地 `.env`。

## 路径与配置核对

| 项目 | 已核实的仓库事实 | 本轮未证明的部分 |
| --- | --- | --- |
| 产品路径 | Java Agent 编排；Java Recommend/Catalog 提供候选/事实；Python 承担算法、评测、训练及模型服务 | 未连接远程实例做当前运行配置核验 |
| 本地默认 | 推荐 Adapter 为 memory；Hot Session State 默认 memory/15m；持久化、Trace、约束解码默认关闭 | 不能据此推断部署实例也关闭 |
| 部署 Compose | 推荐 HTTP、Redis 热状态、会话持久化、Trace；具体开关仍由运行环境覆盖 | Compose 文件存在不等于实例已生效 |
| 推荐模型 | 最终三塔预设为 `product_three_tower_final_v1`、1024 维、主候选份额 0.65、旧保护位 0、查询塔开启 | 依据 10-13 运行报告和预设，本轮未重新验收模型/索引端点 |
| 召回与排序 | 三塔覆盖预设、通用示例和 Python Route Registry 的用途不同；通用示例仍有旧 64 维双塔参数 | 不将旧示例误作三塔正在使用的参数；精粗排开关也不能只凭类存在推断 |
| Skill | 内置澄清、显式需求、冷启动、反馈适应、证据解释、A2UI 六项；默认购物 Profile 限定 recommend/rag-explain/session-memory | 未完成不可变版本、撤销与外部 Runtime 覆盖审计 |

模型的历史依据见 [最终三塔报告](../product-three-tower-final/RESULTS.txt)。Python 的 Route Registry 继续承担原治理职责，本轮没有替换路由或晋级模型。

## 验证结果

| 检查 | 结果与范围 |
| --- | --- |
| 初始 Java 全量 `mvn test` | 711 项收集，710 通过、1 跳过，0 失败/错误 |
| 新增 Java API 固定验收 | 7 项通过；实际 Controller/推荐/反馈，存储与检索使用测试 Adapter |
| 修改后的 Agent 与上游 `mvn ... -pl rs-service-agent -am package` | Agent 模块 239 项，238 通过、1 跳过；上游模块通过；打包成功 |
| 初始 Python CI 选择范围 | 1197 通过、3 跳过；初始静态检查和规范检查失败，见下文 |
| 指标/Skill/在线评测专项 | 64 项通过，显式使用 JDK 21 与打包后的 Java；包含真实 Java Loop → 本地受控 HTTP 工具/评测链路，非真实模型效果 |
| 扩大后的 Python CI 选择范围 | 结果见 [checks.json](checks.json)，包含新增分类后的既有用例 |
| Ruff | 修复一个历史未使用导入后，原 CI 范围及新增代码通过 |
| 工程规范 | 仍有 36 条历史问题；没有放宽规则或添加例外绕过 |
| Java 前端 | TypeScript、105 项测试、构建、依赖 audit（0 漏洞）通过 |
| 浏览器用户流程 | 历史恢复、刷新续聊、中断、原消息重试、A2UI 恢复、降级提示、反馈后重试、409/410、撤回、偏好删除/清空均通过 |
| Python 前端 | TypeScript 通过 |
| 根目录部署/模型启动契约 | 56 项通过 |

环境为 Windows、Python 3.13.14、JDK 21.0.5；CI 的 Python 是 3.11，本轮不宣称两者版本完全一致。Java 编译日志的历史中文编码显示问题不影响测试结果。

跨语言测试必须等 Java 构建完成后运行；本轮首次并行启动时遇到缺少打包 jar / 编译中类指纹变化，随后顺序构建并重跑 64 项通过。浏览器初次缺少 Headless Shell，安装后重跑通过；本机 5173 端口受限，测试改用 15173，没有修改产品配置。

## 仍未通过的历史门禁

初始规范检查为 6 条 `script_main_guard` 和 32 条 `test_file_marker_required`。本轮把两个与 Agent 验收直接相关的测试文件纳入门禁，剩 6 + 30 条，逐条保存在 [engineering-contract-violations.txt](engineering-contract-violations.txt)。其中 6 个模型辅助模块是被其他脚本导入的定义文件；后续需要明确脚本入口与库文件的约束，不能加空 main 仅为了消除报错。其余测试需按实际依赖和资源消耗分类，不能全部盲标 unit。

所以这是一份**存在已知规范缺口、可重复本地验证的开发基线**，不是全绿发布版本。没有运行全量训练、没有部署服务、没有改简历，也没有处理 AgentTeam。

## 后续接续位置

[实施计划](../../superpowers/plans/2026-10-18-agent-capability-completion.md) 的 P0.2–P0.4 本地工作已交付；P0.1 的远程实际配置核验仍待补。P1 当前只交付 usage 缺失语义修正，还需完成每次模型调用的稳定 ID、最终快照、失败/取消记录、摘要/Judge 覆盖和异步观测导出。SDK 已经将部分普通 token 缺失归一为 0 的信息，不能靠本次 Mapper 修复恢复；最终工具提前停止时也可能没有收到末尾 usage，必须显式记录覆盖率。不能把尚未覆盖的调用算成 0 成本。
