# 前端部署与访问

前端构建目录为 `java_agent/frontend`。Nginx 提供静态页面、SPA 深层路由回退，并将同源 `/api/` 转发到 Java Gateway；流式响应关闭代理缓冲。

## 构建和部署

在 `java_agent/frontend` 执行：

```powershell
npm.cmd run build
npm.cmd test
```

将生成的 `dist/`、本目录的 `nginx.conf` 和 `docker-compose.yml` 放到远端 `/home/luo/RS_agent_java/frontend_deploy/`，再执行：

```bash
cd /home/luo/RS_agent_java/frontend_deploy
docker compose -p rs-agent-java-frontend up -d
```

容器为 `rs-agent-java-frontend`，加入 `rs-agent-java_default` 网络；远端静态网页入口仅监听 `127.0.0.1:18089`。远端 `18088` 保留为 Java Gateway API 端口。

## 当前电脑访问

从仓库根目录运行：

```powershell
& ./java_agent/frontend/start-remote-preview.ps1
```

浏览器打开 `http://127.0.0.1:18088/`。脚本在后台创建 SSH 隧道，将本机 `18088` 转发到服务器的前端 `18089`；API 经前端代理访问 Gateway，因此页面与接口同源。脚本检测端口占用，重复执行会复用已经可用的入口。

电脑重启或 SSH 断开后重新运行脚本。该地址供当前电脑使用，尚未绑定公网域名。不要同时用其他 SSH 隧道将本机 `18088` 指向服务器 API 的 `18088`。

## 2026-09-06 验收

- 前端 TypeScript/Vite 构建通过，21 项测试通过。
- Nginx 首页 HTTP 200；未登录访问 `/api/auth/me` 返回 401，说明代理接入真实鉴权服务。
- Chromium 实测：手动选择未使用的真实画像注册成功，首页加载 6 个真实商品；刷新后通过 Secure/HttpOnly refresh cookie 恢复登录，商品详情深层链接刷新成功。
- 前端原先发送 `manual`，后端仅接受 `selected`，导致注册 500；已修正选项值，并移除后端尚不支持的人群分组注册选项。
- 浏览器无 JavaScript 异常，验收账号已退出登录；账号与可视曝光记录保留用于审计。
- 本轮未验证 Agent 流式对话全过程或默认随机画像注册性能。

## 首页换批修复

2026-09-06 后续部署修正了首页丢失 `next_cursor` 的问题：换批推进游标，反馈重排保持当前批次，末尾不回到第一页。真实浏览器已验证连续三批共 18 个不同商品，以及第三批不喜欢后过滤并补满。回归脚本为 `java_agent/frontend/scripts/verify-feed-pagination.cjs`；完整说明见仓库 `docs/superpowers/plans/2026-09-06-home-feed-pagination.md`。这项修复没有接入完整个性化召回，首页目前仍使用 Catalog 冷启动候选。
