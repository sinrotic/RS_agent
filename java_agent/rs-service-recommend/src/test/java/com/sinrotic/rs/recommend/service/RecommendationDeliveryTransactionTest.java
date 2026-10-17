package com.sinrotic.rs.recommend.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.recommend.domain.delivery.RecommendationDelivery;
import com.sinrotic.rs.recommend.domain.delivery.RecommendationDeliveryItem;
import com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity;
import com.sinrotic.rs.recommend.service.impl.JdbcRecommendationPersistenceStore;
import org.h2.jdbcx.JdbcDataSource;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class RecommendationDeliveryTransactionTest {
    private JdbcTemplate jdbc;
    private JdbcRecommendationPersistenceStore store;

    @BeforeEach
    void setUp() {
        var source = new JdbcDataSource();
        source.setURL("jdbc:h2:mem:" + UUID.randomUUID() + ";MODE=MySQL;DB_CLOSE_DELAY=-1");
        jdbc = new JdbcTemplate(source);
        jdbc.execute("""
                CREATE TABLE rs_recommendation_delivery (
                  request_id VARCHAR PRIMARY KEY, account_id VARCHAR, profile_user_id VARCHAR, session_id VARCHAR,
                  scene VARCHAR, preference_version BIGINT, created_at TIMESTAMP, expires_at TIMESTAMP)
                """);
        jdbc.execute("""
                CREATE TABLE rs_recommendation_delivery_item (
                  request_id VARCHAR, item_id VARCHAR, rank_no INT, base_score DOUBLE, category VARCHAR,
                  brand VARCHAR, attributes_json VARCHAR, PRIMARY KEY(request_id, item_id))
                """);
        store = new JdbcRecommendationPersistenceStore(jdbc,
                new TransactionTemplate(new DataSourceTransactionManager(source)), new ObjectMapper());
    }

    @Test
    void allItemsRetainOrderAttributesAndIndependentDeliveryIdentity() {
        var items = List.of(item("B002", 1), item("B001", 2), item("B003", 3), item("B004", 4), item("B005", 5));
        var first = delivery("delivery-1", items);
        var second = delivery("delivery-2", items);
        store.save(first);
        store.save(second);
        assertThat(store.findByRequestId("delivery-1")).contains(first);
        assertThat(store.findByRequestId("delivery-2")).contains(second);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM rs_recommendation_delivery_item", Integer.class)).isEqualTo(10);
    }

    @Test
    void invalidItemBatchRollsBackHeaderAndAllItems() {
        assertThatThrownBy(() -> store.save(delivery("delivery-1", List.of(item("B001", 1), item("B001", 2)))))
                .isInstanceOf(RuntimeException.class);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM rs_recommendation_delivery", Integer.class)).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM rs_recommendation_delivery_item", Integer.class)).isZero();
        store.save(delivery("delivery-1", List.of(item("B001", 1))));
        assertThat(store.findByRequestId("delivery-1")).isPresent();
    }

    private RecommendationDelivery delivery(String id, List<RecommendationDeliveryItem> items) {
        return new RecommendationDelivery(id, new RecommendationIdentity("account-1", "profile-1", "session-1"),
                "agent_chat", 7L, items, Instant.parse("2026-10-10T00:00:00Z"), Instant.parse("2026-10-11T00:00:00Z"));
    }

    private RecommendationDeliveryItem item(String id, int rank) {
        return new RecommendationDeliveryItem(id, rank, 0.5, "Mice", "brand", Map.of("wireless", "true"));
    }
}
