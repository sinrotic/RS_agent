package com.sinrotic.rs.recommend.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.sinrotic.rs.recommend.domain.delivery.*;
import com.sinrotic.rs.recommend.domain.feedback.*;
import com.sinrotic.rs.recommend.domain.preference.*;
import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;
import com.sinrotic.rs.recommend.service.impl.*;
import org.h2.jdbcx.JdbcDataSource;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import java.sql.Timestamp;
import java.time.*;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.*;

/** 实际 JDBC 查询、实际投影和 TTL 缓存夹具组成恢复闭环；不依赖正式服务。 */
class PreferenceBoundaryRegressionTest {
    final Instant now = Instant.now();
    final MutableClock clock = new MutableClock(now);
    final ObjectMapper json = new ObjectMapper().registerModule(new JavaTimeModule());

    @Test
    void cacheLossPreservesOpposingPreferencesInEveryActiveSession() {
        var cache = new Cache();var db = new Database();
        var a = event("a","session-a","item",FeedbackEventType.LIKE,1,now.minusSeconds(3600),null);
        var b = event("b","session-b","item",FeedbackEventType.DISLIKE,2,now.minusSeconds(1800),null);
        db.add(a,false);db.add(b,true);cache.store.apply(a);cache.store.apply(b);
        assertEquals("like",preference(cache.store,"session-a","item").eventType());
        assertTrue(db.events.pendingProjectionEvents(100).isEmpty());
        cache.data.clear();cache.deadlines.clear();
        db.worker(cache.store).rebuildCurrentPreferences();
        assertEquals("like",preference(cache.store,"session-a","item").eventType());
        assertEquals("session",preference(cache.store,"session-a","item").scope());
        assertEquals("dislike",preference(cache.store,"session-b","item").eventType());
        assertEquals("dislike",cache.store.loadProfile("profile").itemPreferences().get("item").eventType());
        assertTrue(Math.abs(Duration.between(now,cache.deadlines.get(sessionKey("session-a"))).toMillis()
                - Duration.ofHours(23).toMillis()) < 2);
    }

    @Test
    void activeSessionRestoresOlderItemsWithoutCopyingNewerProfileFeedback() {
        var cache = new Cache();var db = new Database();
        db.add(event("old","session-a","item",FeedbackEventType.DISLIKE,1,now.minus(Duration.ofDays(2)),null),false);
        db.add(event("touch","session-a","other",FeedbackEventType.LIKE,2,now.minusSeconds(3600),null),true);
        db.add(event("new","session-b","item",FeedbackEventType.LIKE,3,now.minusSeconds(1800),null),true);
        db.worker(cache.store).rebuildCurrentPreferences();
        assertEquals("dislike",preference(cache.store,"session-a","item").eventType());
        assertEquals("session",preference(cache.store,"session-a","item").scope());
        assertEquals("like",cache.store.loadProfile("profile").itemPreferences().get("item").eventType());
    }

    @Test
    void rebuildCannotReviveExpiredSessionOrExtendRemainingLifetime() {
        var cache = new Cache();var db = new Database();
        db.add(event("old","old-session","item",FeedbackEventType.LIKE,1,now.minus(Duration.ofDays(2)),null),true);
        var worker = db.worker(cache.store);worker.rebuildCurrentPreferences();
        assertFalse(cache.data.containsKey(sessionKey("old-session")));
        assertEquals("profile",preference(cache.store,"old-session","item").scope());
        var active = event("active","active-session","other",FeedbackEventType.LIKE,2,now.minusSeconds(3600),null);
        db.add(active,true);worker.rebuildCurrentPreferences();
        var originalDeadline = cache.deadlines.get(sessionKey("active-session"));
        clock.instant = now.plusSeconds(7200);worker.rebuildCurrentPreferences();
        assertEquals(originalDeadline,cache.deadlines.get(sessionKey("active-session")));
        clock.instant = originalDeadline;worker.rebuildCurrentPreferences();
        assertEquals("profile",preference(cache.store,"active-session","other").scope());
    }

    @Test
    void profileExpiryIsPerItemAndDelayedEventsCannotResurrectIt() throws Exception {
        var cache = new Cache();
        var expired = new ItemPreference("old","like","old-item","category","brand",Map.of(),1,
                now.minus(Duration.ofDays(181)),"profile");
        cache.data.put("rs:pref:v2:profile:profile",json.writeValueAsString(
                new OnlinePreferenceSnapshot(1,Map.of("old-item",expired),List.of("old"))));
        cache.store.apply(event("fresh","session","new-item",FeedbackEventType.LIKE,2,now,null));
        assertEquals(Set.of("new-item"),cache.store.loadProfile("profile").itemPreferences().keySet());
        cache.store.apply(event("old","session","old-item",FeedbackEventType.LIKE,1,expired.updatedAt(),null));
        assertFalse(cache.store.loadProfile("profile").itemPreferences().containsKey("old-item"));
        clock.instant = now.plus(Duration.ofDays(180));
        assertTrue(cache.store.loadProfile("profile").itemPreferences().isEmpty());
    }

    @Test
    void reversalRecoversProfileAndSessionIndependentlyAndKeepsTombstone() {
        var cache = new Cache();var db = new Database();
        var a = event("a","session-a","item",FeedbackEventType.LIKE,1,now.minusSeconds(30),null);
        var b = event("b","session-b","item",FeedbackEventType.DISLIKE,2,now.minusSeconds(20),null);
        var reversal = event("reverse","session-b","item",FeedbackEventType.REVERSAL,3,now.minusSeconds(10),"b");
        db.add(a,false);db.add(b,false);db.add(reversal,true);
        db.worker(cache.store).rebuildCurrentPreferences();
        assertEquals("like",preference(cache.store,"session-a","item").eventType());
        assertEquals("profile",preference(cache.store,"session-b","item").scope());
        cache.store.apply(b);
        assertEquals("profile",preference(cache.store,"session-b","item").scope());
        assertEquals(3,cache.store.loadProfile("profile").itemVersions().get("item"));
    }

    @Test
    void sessionReversalRestoresItsOwnEarlierEventWhileProfileKeepsOtherSession() {
        var cache = new Cache();var db = new Database();
        var a = event("a","session-a","item",FeedbackEventType.LIKE,1,now.minusSeconds(40),null);
        var b = event("b","session-a","item",FeedbackEventType.DISLIKE,2,now.minusSeconds(30),null);
        var c = event("c","session-b","item",FeedbackEventType.DISLIKE,3,now.minusSeconds(20),null);
        var reversal = event("reverse","session-a","item",FeedbackEventType.REVERSAL,4,now.minusSeconds(10),"b");
        db.add(a,false);db.add(b,false);db.add(c,false);db.add(reversal,true);
        db.worker(cache.store).rebuildCurrentPreferences();
        assertEquals("like",preference(cache.store,"session-a","item").eventType());
        assertEquals("dislike",cache.store.loadProfile("profile").itemPreferences().get("item").eventType());
        assertEquals("a",db.events.previousSessionExplicitEvent(b).orElseThrow().eventId());
    }

    @Test
    void sessionQueryPaginatesByProfileSessionAndItem() {
        var db = new Database();
        for (int i=0;i<1001;i++) db.add(event("event-"+i,i==1000 ? "session-b" : "session-a",
                String.format("item-%04d",i),FeedbackEventType.LIKE,i+1,now,null),true);
        var first = db.events.rebuildableSessionPreferences("","","",now.minus(Duration.ofHours(24)),1000);
        assertEquals(1000,first.size());
        var cursor = first.getLast().event();
        var last = db.events.rebuildableSessionPreferences(cursor.identity().profileUserId(),cursor.identity().sessionId(),
                cursor.item().itemId(),now.minus(Duration.ofHours(24)),1000);
        assertEquals(1,last.size());assertEquals("session-b",last.getFirst().event().identity().sessionId());
    }

    @Test
    void profileDecayUsesHalfLifeButSessionWeightAndExpiryRemainDistinct() {
        var ranker = new PreferenceAwareFinalReranker(clock,30);
        double fresh = adjustment(ranker,"profile",now);
        assertEquals(fresh/2,adjustment(ranker,"profile",now.minus(Duration.ofDays(30))),1e-12);
        assertEquals(fresh/8,adjustment(ranker,"profile",now.minus(Duration.ofDays(90))),1e-12);
        assertEquals(0,adjustment(ranker,"profile",now.minus(Duration.ofDays(180))),1e-12);
        assertEquals(adjustment(ranker,"session",now),adjustment(ranker,"session",now.minus(Duration.ofDays(90))),1e-12);
        assertEquals(fresh/4,adjustment(new PreferenceAwareFinalReranker(clock,15),"profile",now.minus(Duration.ofDays(30))),1e-12);
        assertThrows(IllegalArgumentException.class,() -> new PreferenceAwareFinalReranker(clock,0));
    }

    @Test
    void legacySessionJsonWithoutExpiryStillLoadsAndCannotKeepExpiredStrongPreference() throws Exception {
        var cache = new Cache();
        var recent = new ItemPreference("recent","like","item","category","brand",Map.of(),1,now.minusSeconds(3600),"session");
        var value = json.valueToTree(new OnlinePreferenceSnapshot(1,Map.of("item",recent),List.of("recent")));
        ((com.fasterxml.jackson.databind.node.ObjectNode)value).remove("expiresAt");
        cache.data.put(sessionKey("legacy"),json.writeValueAsString(value));
        assertEquals("session",preference(cache.store,"legacy","item").scope());
        clock.instant = now.plus(Duration.ofHours(23));
        assertNull(preference(cache.store,"legacy","item"));
    }

    @Test
    void legacyDeletionSnapshotKeepsItsVersionGuardAgainstDelayedFeedback() throws Exception {
        var cache = new Cache();
        var value = json.valueToTree(new OnlinePreferenceSnapshot(5,Map.of(),List.of("deleted"),Map.of("item",5L)));
        ((com.fasterxml.jackson.databind.node.ObjectNode)value).remove("expiresAt");
        cache.data.put(sessionKey("legacy"),json.writeValueAsString(value));
        cache.data.put("rs:pref:v2:profile:profile",json.writeValueAsString(value));
        cache.store.apply(event("late","legacy","item",FeedbackEventType.LIKE,4,now.minusSeconds(60),null));
        assertNull(preference(cache.store,"legacy","item"));
        assertEquals(5,cache.store.loadProfile("profile").itemVersions().get("item"));
    }

    @Test
    void memoryAndRedisShareExpiryAndSessionReversalRules() {
        var cache = new Cache();
        for (OnlinePreferenceStore store : List.of(cache.store,new InMemoryOnlinePreferenceStore(clock))) {
            var own = event("own","session-a","item",FeedbackEventType.DISLIKE,1,now.minusSeconds(30),null);
            var other = event("other","session-b","item",FeedbackEventType.LIKE,2,now.minusSeconds(20),null);
            var reversal = event("reversal","session-a","item",FeedbackEventType.REVERSAL,3,now,"own");
            store.apply(own);store.apply(other);store.applyReversal(reversal,other,null);
            assertEquals("profile",preference(store,"session-a","item").scope());
            assertEquals("session",preference(store,"session-b","item").scope());
            clock.instant = now.plus(Duration.ofHours(24));
            assertEquals("profile",preference(store,"session-b","item").scope());
            clock.instant = now.plus(Duration.ofDays(180));
            assertTrue(store.loadProfile("profile").itemPreferences().isEmpty());
            clock.instant = now;
        }
    }

    @Test
    void sessionRecoveryContinuesPastFailedItemAndRetriesItOnNextCycle() {
        var db = new Database();var cache = new Cache();
        var a = event("a","session-a","first",FeedbackEventType.LIKE,1,now,null);
        var b = event("b","session-a","second",FeedbackEventType.LIKE,2,now,null);
        db.add(a,true);db.add(b,true);
        OnlinePreferenceStore store = spy(cache.store);
        doThrow(new IllegalStateException("模拟写入失败")).doCallRealMethod()
                .when(store).restoreSession(argThat(e -> e.eventId().equals("a")),isNull(),any());
        var worker = db.worker(store);worker.rebuildCurrentPreferences();
        assertEquals("profile",preference(store,"session-a","first").scope());
        assertEquals("session",preference(store,"session-a","second").scope());
        worker.rebuildCurrentPreferences();
        assertEquals("session",preference(store,"session-a","first").scope());
        assertEquals("session",preference(store,"session-a","second").scope());
    }

    double adjustment(PreferenceAwareFinalReranker ranker,String scope,Instant at) {
        var p = new ItemPreference("feedback","like","source","category","brand",Map.of(),1,at,scope);
        var candidate = new ItemEmbeddingText("candidate","text","title","category","category","brand",null,Map.of());
        return ranker.rerank(List.of(candidate),new OnlinePreferenceSnapshot(1,Map.of("source",p),List.of("feedback")),1)
                .getFirst().preferenceAdjustment();
    }
    ItemPreference preference(OnlinePreferenceStore store,String session,String item) {
        return store.load(new RecommendationIdentity("account","profile",session)).itemPreferences().get(item);
    }
    String sessionKey(String session) {return "rs:pref:v2:session:profile:"+session;}
    RecommendationFeedbackEvent event(String id,String session,String item,FeedbackEventType type,long version,Instant at,String target) {
        return new RecommendationFeedbackEvent(id,id,"request-"+id,new RecommendationIdentity("account","profile",session),
                new RecommendationDeliveryItem(item,1,1,"category","brand",Map.of()),type,target,at,at,version);
    }
    class Cache {
        final Map<String,String> data = new HashMap<>();final Map<String,Instant> deadlines = new HashMap<>();
        final RedisOnlinePreferenceStore store;
        @SuppressWarnings("unchecked") Cache() {
            ValueOperations<String,String> values = mock(ValueOperations.class);
            when(values.get(anyString())).thenAnswer(i -> {
                String key = i.getArgument(0);
                if (deadlines.containsKey(key) && !deadlines.get(key).isAfter(clock.instant())) {
                    data.remove(key);deadlines.remove(key);
                }
                return data.get(key);
            });
            var redis = mock(StringRedisTemplate.class,i -> {
                if (i.getMethod().getName().equals("execute")) {
                    String key = ((List<String>)i.getArgument(1)).getFirst();String expected = i.getArgument(2);
                    if (!Objects.equals(data.getOrDefault(key,""),expected)) return 0L;
                    data.put(key,i.getArgument(3));deadlines.put(key,clock.instant().plusMillis(Long.parseLong(i.getArgument(4))));
                    return 1L;
                }
                return RETURNS_DEFAULTS.answer(i);
            });
            when(redis.opsForValue()).thenReturn(values);store = new RedisOnlinePreferenceStore(redis,json,clock);
        }
    }
    class Database {
        final JdbcTemplate jdbc;final JdbcRecommendationPersistenceStore events;
        Database() {
            var ds = new JdbcDataSource();ds.setURL("jdbc:h2:mem:preferences-"+UUID.randomUUID()+";MODE=MySQL;DB_CLOSE_DELAY=-1");
            jdbc = new JdbcTemplate(ds);
            jdbc.execute("""
                CREATE TABLE rs_recommend_feedback_event (
                  event_id VARCHAR PRIMARY KEY,idempotency_key VARCHAR,request_id VARCHAR,account_id VARCHAR,
                  profile_user_id VARCHAR,session_id VARCHAR,item_id VARCHAR,category VARCHAR,brand VARCHAR,
                  attributes_json VARCHAR,event_type VARCHAR,reverses_event_id VARCHAR,occurred_at TIMESTAMP,
                  received_at TIMESTAMP,preference_version BIGINT,position_no INT,visible_ratio DOUBLE,visible_duration_ms BIGINT)
                """);
            jdbc.execute("CREATE TABLE rs_profile_item_preference_projection (profile_user_id VARCHAR,item_id VARCHAR,latest_event_id VARCHAR,expires_at TIMESTAMP)");
            jdbc.execute("CREATE TABLE rs_recommend_feedback_outbox (event_id VARCHAR,status VARCHAR,next_attempt_at TIMESTAMP,created_at TIMESTAMP)");
            events = new JdbcRecommendationPersistenceStore(jdbc,new TransactionTemplate(new DataSourceTransactionManager(ds)),json);
        }
        void add(RecommendationFeedbackEvent e,boolean latest) {
            jdbc.update("""
                INSERT INTO rs_recommend_feedback_event (event_id,idempotency_key,request_id,account_id,profile_user_id,
                session_id,item_id,category,brand,attributes_json,event_type,reverses_event_id,occurred_at,received_at,preference_version)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,e.eventId(),e.idempotencyKey(),e.requestId(),e.identity().accountId(),e.identity().profileUserId(),
                e.identity().sessionId(),e.item().itemId(),e.item().category(),e.item().brand(),"{}",e.eventType().apiValue(),
                e.reversesEventId(),Timestamp.from(e.occurredAt()),Timestamp.from(e.receivedAt()),e.preferenceVersion());
            jdbc.update("INSERT INTO rs_recommend_feedback_outbox VALUES (?,'APPLIED',?,?)",
                    e.eventId(),Timestamp.from(e.receivedAt()),Timestamp.from(e.receivedAt()));
            if (latest) jdbc.update("INSERT INTO rs_profile_item_preference_projection VALUES (?,?,?,?)",
                    e.identity().profileUserId(),e.item().itemId(),e.eventId(),Timestamp.from(e.receivedAt().plus(Duration.ofDays(180))));
        }
        FeedbackProjectionRetryWorker worker(OnlinePreferenceStore store) {
            return new FeedbackProjectionRetryWorker(events,store,mock(RecommendationFeedbackMetrics.class),clock);
        }
    }
    static class MutableClock extends Clock {
        Instant instant;MutableClock(Instant instant) {this.instant = instant;}
        public Instant instant() {return instant;}
        public ZoneId getZone() {return ZoneOffset.UTC;}
        public Clock withZone(ZoneId zone) {return this;}
    }
}
