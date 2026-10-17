# 2026-09-05 远端服务验收记录

本文保留修复前的实测结果。后续已完成部署和复验，最新状态见 [远端服务修复与验收](2026-09-05-remote-service-repair.md)。

## 结论

通过 SSH 别名 `server` 对现有部署进行 HTTP 和 MySQL 实测。当前不能通过 Gateway 反馈闭环验收：会话创建返回 404，可信身份未传递，反馈返回 APPLIED 但未写入权威数据库。直连 Recommend 的显式反馈行为能够运行，但属于隔离诊断，不等于浏览器或 Gateway 链路通过。

本次没有部署 JAR、重启服务、停止 Redis、迁移或删除业务数据。此前本地修复尚不能视为远端已生效。

## 实测结果

| 检查 | 结果 | 证据与影响 |
| --- | --- | --- |
| 服务连通 | 部分通过 | Recommend、Agent readiness 返回 200 / UP；Gateway、User、Catalog、Model、Platform Trace 的 readiness 或 health 探针返回 404，不能据此认定进程不可用 |
| Catalog 数据投影 | 通过 | 最新投影任务 COMPLETED，processed_rows = source_rows = 887002 |
| Gateway 注册 | 通过 | 使用两个独立验收账号，绑定此前未绑定账号、未产生反馈的导入画像；注册返回 200 |
| Gateway 会话创建 | 失败 | POST /api/sessions 返回 404；直连 User 同一路径也返回 404 |
| Gateway 首页及偏好查询 | 失败 | 携带注册取得的真实 Bearer token，POST /api/recommend/home 和 GET /api/recommend/preferences 均返回 400 |
| 身份传递诊断 | 已定位症状 | Recommend 日志分别报告缺少 X-Account-Id、X-Profile-User-Id；远端 Gateway 未设置 RS_GATEWAY_AUTH_TOKEN_VALIDATION，JAR 内默认配置是 presence |
| 直连 Recommend 首页 | 通过 | 使用随机 audit UUID 身份及会话，初始返回 5 个商品 |
| 可视曝光 API | 通过 | 返回 accepted=true、application_status=NOT_APPLICABLE；仅验证 HTTP 契约，未模拟浏览器可视观察 |
| 喜欢及幂等 | 通过 | 返回 APPLIED，重复请求反馈 ID 不变、duplicate=true；正确刷新后商品分数提高，反馈事件 ID 和版本可见 |
| 不喜欢及幂等 | 部分通过 | 商品被过滤、重复请求保持幂等；但页面从 5 条变为 4 条，has_more 错误变为 false，本地分页修复需部署 |
| 撤销 | 通过 | 按逆序撤销本次显式反馈，偏好列表为空，商品重新出现 |
| MySQL 权威持久化 | 失败 | 直连诊断的 like/dislike 返回 APPLIED 后，按独立验收身份查询交付表、事件表、偏好投影表，计数均为 0；容器未设置 JDBC/Redis 反馈模式 |
| 真实 embedding 运行时 | 健康通过 | http://172.21.0.1:18115/health 返回 UP、cuda、dimension=1024；本轮没有执行真实 embedding 推理 |
| 真实重排接口 | 失败 | 同一运行时 POST /internal/model/rank 返回 404 |
| Java Model 健康报告 | 失败 | /api/model/health 仍返回 10 个启用模型及全部 UP，与重排运行时缺失不一致 |

## 探针修正与边界

- BGE 仅监听 Docker 网桥地址 172.21.0.1:18115；对 127.0.0.1 的连接拒绝不算模型宕机，改用实际配置地址后健康请求成功。
- 最初诊断误把任意字符串当作 refresh_token，返回空页；按现有契约改成 rerecall_pool500 后重跑。上表反馈效果使用修正后的请求，不将错误探针造成的空页作为服务缺陷。
- 注册得到的账号在测试结束调用 logout；保留两个带 audit_ 前缀的验收账号记录。没有写入这些账号绑定画像的显式偏好。
- 直连诊断另用随机 audit UUID，所有成功创建的喜欢／不喜欢事件均已撤销，并核对偏好为空。
- 未验证真实 Redis Lua、偏好重建、服务重启后恢复、Scylla 会话恢复、浏览器 SSE、压测及 GPU 推理延迟。
- 本轮发现的权威表原本为空；不能据此声称已经完成历史偏好迁移或恢复验证。

## 下一步顺序

1. 将当前本地修复打包，核对远端 Compose 与 JAR 版本；优先同步 Gateway、User、Recommend。保留现有部署的回滚副本和实际凭据配置。
2. 配置 Gateway 使用 Redis token 校验，验证注册／登录后可信账号与画像身份能传递；验证 User 会话接口返回成功。
3. 启用 Recommend 的 JDBC 持久化和 Redis 投影，先确认一次交付与反馈确实落库，再判断 APPLIED/PENDING、撤销、v2 偏好重建是否正确。
4. 部署 Model 的真实适配器和健康检查修复；有本地 reranker 权重与资源预算后启用重排运行时。
5. 完整 Gateway smoke 通过后，再在受控范围执行 Redis 故障恢复及会话重启验收。

相关本地实现与测试见 [服务可靠性修复记录](2026-09-05-service-reliability-repairs.md)。
