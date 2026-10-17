# 服务缺口修复与验证

本轮按“离线服务先不用管”的范围，修复会话生命周期、冷启动上下文、流式错误、反馈后生成重试、进程内会话缓存和执行通道竞态。另补齐历史读取的账号归属校验，处理前端开发依赖漏洞与窄屏导航溢出。正式服务没有启动、重启或替换；验收用的临时 MySQL 已删除。

## 修复后的行为

| 原问题 | 修复结果 | 验证 |
| --- | --- | --- |
| 聊天不更新 Session 活动时间，24 小时无活动仍可续聊 | User 服务按 Account、Profile User、ACTIVE 状态及活动边界条件原子准入，更新活动时间和最后需求；恰好满 24 小时按过期处理；已结束 Session 返回 410 | 固定时钟边界、结束与刷新竞争、内部 HTTP 契约，以及隔离 MySQL 的实际 Mapper SQL |
| 页面恢复历史后，模型丢失前文约束 | 每个新 Turn 接入 Transcript Recovery，重建 Checkpoint 摘要、原样保留的对话和 Transcript 尾部；Redis 快照不是恢复前提 | 服务对象重建、无 Redis 快照续聊、摘要与尾部恢复 |
| SSE 把 409 等状态改成通用失败 | `error` 携带状态、固定错误码和可重试标志；前端保留类型，409 提供刷新历史，410/404 切为只读 | Controller、客户端及浏览器流程；覆盖归属异常原本误变 500 的路径 |
| 反馈已应用，但随后生成失败仍提示“反馈更新失败” | 保存反馈与生成结果分别确认；生成失败明确显示“反馈已保存”，保留同一 `client_turn_id`，重试只调用 Agent | 浏览器先接收 APPLIED 再断流，重试成功后反馈提交次数仍为 1 |
| 会话历史和归属 Map 无界增长 | 合并为一个有权重预算、访问过期的缓存，以持久 Transcript 最新序号校验缓存；淘汰后恢复归属、历史和下一轮次 | 300 个 Session 压力夹具，缓存保留不超过 256 个，淘汰后恢复及越权检查 |
| 执行通道清理与新请求登记竞态 | 在同一 Session 的 Map 原子操作内登记和清理，保留已有执行/等待请求的通道；队列计数使用登记时的值 | 固定时序夹具先复现同会话并发数为 2，修复后为 1 |

模型侧恢复的历史对话预算为 6000 个字符。摘要、早期需求和近期对话按完整消息组选择，超预算时不截断半条消息；记录 `CONTEXT_TRUNCATED` 并给模型澄清缺失需求的提示。裁剪只影响当前上下文，不删除持久历史。该字符预算不等于模型的 token 容量验收。

会话视图缓存的权重预算为 8 MiB，每条视图最小权重 32 KiB，访问后 30 分钟过期。权重是根据内容估算的缓存预算，不代表整个 JVM 堆的硬上限。正式持久模式继续以 Scylla Transcript 为权威事实；读取最新序号使用存储层的 `latest` 查询。

## 归属与旧数据兼容

公开 `/api/agent/sessions/{id}/history` 与旧 `/turns` 入口都要求 Gateway 注入 Account、Profile User，并校验二者。发现同一画像、不同账号会错误返回 200 的路径后，已加入真实编排服务的 Controller 回归。

旧 Transcript 可能没有 Account 字段，历史读取和已确认结果的重试会回查 User 的 Session 归属。此查询不刷新活动时间；已结束 Session 仍可查看历史和取回已确认的回答，新消息则返回 410。User 归属校验不可用时拒绝放行。

正式 Compose 固定启用 `RS_AGENT_SESSION_LIFECYCLE_ENABLED=true`，并通过 `RS_USER_SERVICE_URL` 访问 User。独立本地 Agent 夹具保留关闭准入的配置，便于内存模式测试。新版本发布需同时更新 User 与 Agent，避免新 Agent 调用尚未存在的准入接口。

## 前端工具链与页面

Tailwind 更新为 4.3.3，改用 `@tailwindcss/postcss`，移除旧 Autoprefixer 依赖；同步迁移渐变、伸缩、阴影、模糊和轮廓工具类。Nanoid 和 Source Map 的传递依赖已更新，`npm audit` 全依赖报告为 0 项漏洞，CI 增加审计步骤。

新版工具链支持的浏览器范围采用 [Tailwind 官方升级说明](https://tailwindcss.com/docs/upgrade-guide)：Chrome 111+、Safari 16.4+、Firefox 128+。页面已检查桌面及 390 像素窄屏，导航换行并限制横向溢出，聊天输入允许缩小；浏览器夹具验证实际渐变样式及窄屏宽度。

## 验收证据

| 检查 | 结果 |
| --- | --- |
| JDK 21 全模块清理后构建 | 509 项测试，508 通过、1 项真实模型 smoke 跳过，0 失败或错误 |
| 前端单元测试与生产构建 | 40 项通过；TypeScript、Vite 构建通过 |
| 浏览器流程及页面 | 历史、刷新、中断、断线重试、反馈保存后生成重试、409/410、A2UI、降级、偏好撤销与清空通过；桌面与窄屏检查通过 |
| 根目录部署检查 | Python 25 项通过，不加载模型 |
| 实际 Mapper SQL | 隔离 MySQL 11 项断言通过，临时容器与数据卷已清理 |
| npm 全依赖审计 | 0 项漏洞；运行依赖包含在此范围内 |
| CI 配置 | 本地解析及审计步骤检查通过，远端 CI 尚未运行 |

日志、审计报告和截图保存在 `outputs/service-completion-20261010/fixes-evidence/`。包含各问题的修复前失败日志、修复后测试结果，以及 `session-lifecycle-mysql.json` 的 11 项数据库断言和临时资源清理结果。

验证命令：

```text
JDK 21: mvn -B clean package
java_agent/frontend: npm test
java_agent/frontend: npm run build
java_agent/frontend: npm run test:e2e
java_agent/frontend: npm audit --json
仓库根目录: python -m pytest tests -q
仓库根目录: python java_agent/deploy/remote/ops/verify_session_lifecycle.py --output outputs/service-completion-20261010/fixes-evidence/session-lifecycle-mysql.json
```

新的发布产物使用独立目录 `outputs/service-completion-20261010/fixes-release/`，保留上一轮发布包。包描述当前含未提交修改的工作区，包含 12 个可执行服务 JAR、前端、SQL 与部署工具，运行密钥不进入包。

## 仍未验收的运行事项

真实模型质量、业务延迟与容量、正式数据库和 Scylla 的完整恢复演练仍需要独立运行验收，本轮测试不代表这些条件已达成。外部支付、退款、物流及公网入口仍按既有业务和部署范围处理。本轮没有把服务离线状态列为修复任务，也没有发布到正式环境。
