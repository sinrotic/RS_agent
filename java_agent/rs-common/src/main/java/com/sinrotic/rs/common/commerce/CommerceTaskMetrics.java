package com.sinrotic.rs.common.commerce;

import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.jdbc.core.JdbcTemplate;

/** SQL 只由指标采集触发，不为订单 ID 创建标签。数据库故障返回 NaN，不能报告为零。 */
public final class CommerceTaskMetrics {
    public static void register(MeterRegistry registry,JdbcTemplate jdbc,String component,String unfinished,String review,String oldest) {
        gauge(registry,jdbc,component,"rs_commerce_tasks_pending",unfinished);
        gauge(registry,jdbc,component,"rs_commerce_tasks_review",review);
        gauge(registry,jdbc,component,"rs_commerce_tasks_oldest_seconds",oldest);
    }
    public static void registerUtc(MeterRegistry registry,JdbcTemplate jdbc,String component,String unfinished,String review,String oldestTimestamp) {
        gauge(registry,jdbc,component,"rs_commerce_tasks_pending",unfinished);
        gauge(registry,jdbc,component,"rs_commerce_tasks_review",review);
        Gauge.builder("rs_commerce_tasks_oldest_seconds",jdbc,db -> {
            try {
                var timestamp=db.queryForObject(oldestTimestamp,java.time.LocalDateTime.class);
                return timestamp==null ? 0 : Math.max(0,java.time.Duration.between(timestamp,java.time.LocalDateTime.now(java.time.Clock.systemUTC())).toSeconds());
            } catch(org.springframework.dao.DataAccessException unavailable) {return Double.NaN;}
        }).tag("component",component).register(registry);
    }
    private static void gauge(MeterRegistry registry,JdbcTemplate jdbc,String component,String name,String sql) {
        Gauge.builder(name,jdbc,db -> {
            try { Number value=db.queryForObject(sql,Number.class);return value==null ? 0 : Math.max(0,value.doubleValue()); }
            catch(org.springframework.dao.DataAccessException unavailable) {return Double.NaN;}
        }).tag("component",component).register(registry);
    }
    private CommerceTaskMetrics() {}
}
