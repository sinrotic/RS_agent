package com.sinrotic.rs.recommend.config;

import com.zaxxer.hikari.HikariDataSource;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import javax.sql.DataSource;

@Configuration
@ConditionalOnProperty(name = "rs.recommend.feedback.persistence", havingValue = "jdbc")
public class RecommendationPersistenceConfiguration {

    @Bean(destroyMethod = "close")
    HikariDataSource recommendationDataSource(
            @Value("${rs.recommend.feedback.jdbc.url}") String url,
            @Value("${rs.recommend.feedback.jdbc.username}") String username,
            @Value("${rs.recommend.feedback.jdbc.password}") String password,
            @Value("${rs.recommend.feedback.jdbc.maximum-pool-size:8}") int maximumPoolSize,
            @Value("${rs.recommend.feedback.jdbc.minimum-idle:2}") int minimumIdle,
            @Value("${rs.recommend.feedback.jdbc.connection-timeout-ms:3000}") long connectionTimeoutMs
    ) {
        HikariDataSource dataSource = new HikariDataSource();
        dataSource.setPoolName("recommendation-mysql");
        dataSource.setDriverClassName("com.mysql.cj.jdbc.Driver");
        dataSource.setJdbcUrl(url);
        dataSource.setUsername(username);
        dataSource.setPassword(password);
        dataSource.setMaximumPoolSize(maximumPoolSize);
        dataSource.setMinimumIdle(minimumIdle);
        dataSource.setConnectionTimeout(connectionTimeoutMs);
        return dataSource;
    }

    @Bean
    JdbcTemplate recommendationJdbcTemplate(DataSource recommendationDataSource) {
        return new JdbcTemplate(recommendationDataSource);
    }

    @Bean
    TransactionTemplate recommendationTransactionTemplate(DataSource recommendationDataSource) {
        return new TransactionTemplate(new DataSourceTransactionManager(recommendationDataSource));
    }
}
