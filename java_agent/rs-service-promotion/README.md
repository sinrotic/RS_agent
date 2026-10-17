# 优惠券服务

第一版提供限量领券、每 Account 每活动一张、单券满减、锁券、核销及取消返还。MySQL 是发行额度和个人券的权威来源；Redis 只保护活动入口。

默认端口 8095；可执行产物为 target/rs-service-promotion-exec.jar。请使用完整工程测试验证跨订单服务的恢复流程。

接口、数据准备、配置与部署见 [交易第一版说明](../../docs/commerce-v1.md)。
