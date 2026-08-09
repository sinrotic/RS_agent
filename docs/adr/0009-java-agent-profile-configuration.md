# Java Agent Profile 配置与默认值来源

## 状态

已接受。

## 决策

Java `rs-service-agent` 首版使用 `application.yml`/Java `@ConfigurationProperties` 选择和覆盖 Agent Profile，不引入模板数据库、动态脚本或新的配置中心。

完整的内置 `shopping-assistant` 默认值由 Java fallback 提供；`application.yml` 只负责选择默认 Profile 或显式覆盖 Profile，避免同一组默认值在两处重复维护。

`AgentProfileRegistry` 将绑定后的配置转换为不可变 `AgentRuntimeProfile`，并在应用启动时拒绝未知默认 Profile、重复 id、缺失引用、空 capability/output allowlist、非法枚举和非法循环次数。

## 兼容性

- 没有 `rs.agent.templates` 配置时继续使用内置 `shopping-assistant`。
- 用户输入不能任意切换服务端 Profile。
- Profile 配置只描述 Runtime 选择和允许范围，不改变 Recommend ranking route、pool500 治理或 Session History 权威来源。
- Capability 执行和公共输出投影由后续模块负责。
