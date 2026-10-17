# RS Agent

这个仓库包含两个相关项目：

- `java_agent`：Java 服务实现，当前主要开发集中在这里。
- `python_agent`：Python Agent 与推荐系统原型代码。

除非任务明确属于 Python Agent，否则新的功能开发和集成修改优先从 `java_agent` 开始。

最近一轮服务缺口的修复、验证与发布包边界见 [2026-10-10 修复记录](docs/service-fixes-20261010.md)。

## 开发知识库

后续迭代先从 [`docs/knowledge-base/README.md`](docs/knowledge-base/README.md) 进入。该入口汇总项目当前状态、领域不变量、系统架构、接口契约、数据事实来源以及开发测试与部署方式；领域词汇仍以根目录 [`CONTEXT.md`](CONTEXT.md) 为准，架构决策仍以 [`docs/adr/`](docs/adr/) 为准。

# 参考

参考文件夹中包含claudecode源码以及一个开源的B2B2C的spring框架
