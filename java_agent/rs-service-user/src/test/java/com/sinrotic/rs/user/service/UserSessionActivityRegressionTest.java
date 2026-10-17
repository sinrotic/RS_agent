package com.sinrotic.rs.user.service;

import com.sinrotic.rs.user.domain.dto.EndUserSessionRequestDTO;
import com.sinrotic.rs.user.mapper.UserSessionMapper;
import org.apache.ibatis.builder.xml.XMLMapperBuilder;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.*;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.h2.jdbcx.JdbcDataSource;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import java.time.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import static org.assertj.core.api.Assertions.*;

class UserSessionActivityRegressionTest {
    @Test
    void browsingRenewsSlidingExpiryAndPreservesLastDialogueQuery() throws Exception {
        try (var f = new Fixture(ZoneOffset.UTC)) {
            f.create(); f.service.admit("account","profile","session-01","预算五百");
            f.clock.hours(23);
            var active = f.service.touch("account","profile","session-01");
            assertThat(active.expiresAt()).isEqualTo(f.clock.origin.plus(Duration.ofHours(47)));
            assertThat(f.mapper.findBySessionId("session-01").getLastUserQuery()).isEqualTo("预算五百");
            f.clock.hours(25);
            assertThat(f.service.get("account","profile","session-01").status()).isEqualTo("ACTIVE");
            f.clock.hours(47);
            assertThatThrownBy(() -> f.service.touch("account","profile","session-01")).hasMessageContaining("410");
            assertThat(f.mapper.findBySessionId("session-01").getStatus()).isEqualTo("ENDED");
        }
    }

    @Test
    void historyAndProjectionActivityReadsDoNotKeepSessionAlive() throws Exception {
        try (var f = new Fixture(ZoneOffset.UTC)) {
            f.create(); f.clock.hours(23);
            assertThat(f.service.activity("account","profile","session-01").expiresAt()).isEqualTo(f.clock.origin.plus(Duration.ofHours(24)));
            f.service.list("account","profile",null,50);
            assertThat(f.mapper.findBySessionId("session-01").getLastActiveAt()).isEqualTo(LocalDateTime.ofInstant(f.clock.origin,ZoneOffset.UTC));
            f.clock.hours(24);
            assertThat(f.service.get("account","profile","session-01").status()).isEqualTo("ENDED");
        }
    }

    @Test
    void activityExpiryUsesUserTimeZoneRatherThanGuessingLocalTimeAsUtc() throws Exception {
        try (var f = new Fixture(ZoneOffset.ofHours(8))) {
            f.create();
            assertThat(f.mapper.findBySessionId("session-01").getLastActiveAt().getHour()).isEqualTo(8);
            assertThat(f.service.activity("account","profile","session-01").expiresAt()).isEqualTo(f.clock.origin.plus(Duration.ofHours(24)));
        }
    }

    @Test
    void foreignEndedAndConcurrentEndedSessionsCannotBeTouched() throws Exception {
        try (var f = new Fixture(ZoneOffset.UTC)) {
            f.create(); f.clock.hours(1);
            assertThatThrownBy(() -> f.service.touch("other","profile","session-01")).hasMessageContaining("404");
            assertThatThrownBy(() -> f.service.touch("account","other","session-01")).hasMessageContaining("404");
            f.service.end("account","profile",new EndUserSessionRequestDTO("session-01","manual"));
            assertThatThrownBy(() -> f.service.touch("account","profile","session-01")).hasMessageContaining("410");
            var now = LocalDateTime.now(f.clock);
            assertThat(f.mapper.touchSession("session-01","account","profile",now,now.minusHours(24))).isZero();
            assertThat(f.mapper.findBySessionId("session-01").getStatus()).isEqualTo("ENDED");
        }
    }

    @Test
    void delayedSqlActivityCannotMoveLastActiveTimeBackwards() throws Exception {
        try (var f = new Fixture(ZoneOffset.UTC)) {
            f.create(); f.clock.hours(23); f.service.touch("account","profile","session-01");
            var active = LocalDateTime.now(f.clock);
            f.mapper.touchSession("session-01","account","profile",active.minusHours(1),active.minusHours(25));
            assertThat(f.mapper.findBySessionId("session-01").getLastActiveAt()).isEqualTo(active);
            assertThat(f.mapper.touchSession("session-01","other","profile",active,active.minusHours(24))).isZero();
        }
    }

    @Test
    void activeSessionScanIsBoundedOrderedAndDoesNotReviveInactiveSessions() throws Exception {
        try (var f = new Fixture(ZoneOffset.UTC)) {
            f.create(); f.create(); f.create();
            f.service.end("account","profile",new EndUserSessionRequestDTO("session-01","manual"));
            assertThat(f.service.activeSessions("",1)).extracting("sessionId").containsExactly("session-02");
            assertThat(f.service.activeSessions("session-02",50)).extracting("sessionId").containsExactly("session-03");
            assertThatThrownBy(() -> f.service.activeSessions("",101)).hasMessageContaining("400");
            f.clock.hours(24);
            assertThat(f.service.activeSessions("",50)).isEmpty();
            assertThat(f.mapper.findBySessionId("session-02").getLastActiveAt()).isEqualTo(LocalDateTime.ofInstant(f.clock.origin,ZoneOffset.UTC));
        }
    }

    static class MutableClock extends Clock {
        final Instant origin = Instant.parse("2026-10-11T00:00:00Z");
        Instant now = origin;
        final ZoneId zone;
        MutableClock(ZoneId zone) { this.zone = zone; }
        public Instant instant() { return now; }
        public ZoneId getZone() { return zone; }
        public Clock withZone(ZoneId newZone) { var result = new MutableClock(newZone);result.now = now;return result; }
        void hours(int hours) { now = origin.plus(Duration.ofHours(hours)); }
    }

    static class Fixture implements AutoCloseable {
        final MutableClock clock;
        final SqlSession session;
        final UserSessionMapper mapper;
        final UserSessionService service;
        Fixture(ZoneId zone) throws Exception {
            clock = new MutableClock(zone);
            var data = new JdbcDataSource(); data.setURL("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DB_CLOSE_DELAY=-1");
            new JdbcTemplate(data).execute("""
                    CREATE TABLE rs_user_session(session_id VARCHAR PRIMARY KEY,account_id VARCHAR,profile_user_id VARCHAR,
                    entry_scene VARCHAR,active_preferences_json VARCHAR,last_user_query VARCHAR,started_at TIMESTAMP,
                    last_active_at TIMESTAMP,status VARCHAR,end_reason VARCHAR,ended_at TIMESTAMP)
                    """);
            var config = new Configuration(new Environment("test",new JdbcTransactionFactory(),data));
            try (var xml = getClass().getClassLoader().getResourceAsStream("mapper/UserSessionMapper.xml")) {
                new XMLMapperBuilder(xml,config,"mapper/UserSessionMapper.xml",config.getSqlFragments()).parse();
            }
            session = new SqlSessionFactoryBuilder().build(config).openSession(true);
            mapper = session.getMapper(UserSessionMapper.class);
            var sequence = new AtomicInteger();
            service = new UserSessionService(mapper,clock,() -> String.format("session-%02d",sequence.incrementAndGet()));
        }
        void create() { service.create("account","profile",null); }
        public void close() { session.close(); }
    }
}
