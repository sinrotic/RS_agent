# 2026-09-06 首页换批重复修复

> 后续状态：2026-09-07 已接入画像／反馈召回、真实 BGE 排序及跨会话去重。本文保留当时的问题记录，当前行为与验收结果见 [首页个性化与服务收口](2026-09-07-personalized-home-completion.md)。

## 症状和根因

真实 Gateway 请求及 Chromium 点击均复现：首次加载和“换一批”返回相同的六个商品，起始商品为 `0000306002`。后端已返回 `next_cursor`，但 MallHome 没有保存；刷新只发送 `rerecall_pool500`，被服务端按空游标处理，因此每次从目录开头读取。

## 修复

- 保存当前批次起点、下一批游标和 `has_more`。
- “换一批”发送下一批游标，成功后推进当前批次起点。
- 喜欢／不喜欢后的刷新发送当前批次起点，继续依据真实偏好重排，避免跳回第一页。
- 到达末尾时禁用真实模式的换批按钮，显示“已浏览完当前商品”；空批次且仍有下一页时允许继续。
- 保留 Mock 模式的演示换批行为。

本轮修改前端并部署到远端 Nginx，没有更换 Java JAR。原前端构建保存在 `/home/luo/RS_agent_java/backups/20260906-feed-rotation/dist`。

## 验收

- 修复前，真实浏览器断言“下一批不能与上一批重叠”失败；部署后同一断言通过。
- TypeScript/Vite 构建及已有 21 项测试通过。
- 新增 `java_agent/frontend/scripts/verify-feed-pagination.cjs`，使用真实注册、Gateway、Catalog 和反馈服务。验证连续三批共 18 个不同商品；第三批提交不喜欢后过滤并补满，仍停留在第三批范围，反馈事件 ID 可见。
- 浏览器无 JavaScript 异常，测试反馈已撤销，验收账号已登出。

回归脚本需要 Playwright、浏览器和独立验收画像。通过 `RS_PLAYWRIGHT_MODULE` 指定已安装的 Playwright 模块路径，`RS_CHROMIUM_PATH` 可指定 Chromium 可执行文件，`RS_E2E_PROFILE_ID` 必须是分配给验收的空闲画像；然后执行：

```powershell
node java_agent/frontend/scripts/verify-feed-pagination.cjs
```

当前访问地址仍为 `http://127.0.0.1:18088/`，刷新页面加载新构建即可。

## 范围

此修复消除换批和反馈后返回第一页的错误。首页候选仍来自 Catalog 冷启动顺序扫描；首次加载可能相同，连续批次也可能包含相近类目。完整的画像召回、候选多样化和模型排序尚未接入首页，本轮没有将其他实验产物提升为主推荐源。
