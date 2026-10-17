package com.sinrotic.rs.payment.service;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.stereotype.Component;
import java.sql.Statement;
import java.util.Objects;

/** 数据库分配支付编号；跨进程共用序列，进程重启不会复用旧编号。 */
@Component
public class DatabaseIdGenerator implements IdGenerator {
    private final JdbcTemplate jdbc;

    public DatabaseIdGenerator(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    @Override
    public long nextId() {
        GeneratedKeyHolder key = new GeneratedKeyHolder();
        jdbc.update(connection -> connection.prepareStatement(
                "INSERT INTO payment_id(marker) VALUES (1)", Statement.RETURN_GENERATED_KEYS),key);
        return Objects.requireNonNull(key.getKey(),"数据库未返回支付编号").longValue();
    }
}
