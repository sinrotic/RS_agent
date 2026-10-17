package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.delivery.*;
import com.sinrotic.rs.recommend.domain.dto.HomeRecommendRequestDTO;
import com.sinrotic.rs.recommend.domain.feedback.*;
import com.sinrotic.rs.recommend.domain.preference.ActiveRecommendationSession;
import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;
import com.sinrotic.rs.recommend.service.impl.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.time.*;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class SessionPreferenceActivityTest {
    static final RecommendationIdentity ID = new RecommendationIdentity("account","profile","session");
    static class MutableClock extends Clock {
        final Instant origin = Instant.now();
        Instant now = origin;
        public Instant instant() { return now; }
        public ZoneId getZone() { return ZoneOffset.UTC; }
        public Clock withZone(ZoneId zone) { return this; }
        void hours(int hours) { now = origin.plus(Duration.ofHours(hours)); }
    }

    @ParameterizedTest
    @ValueSource(booleans = {false,true})
    void activeDialogueRestoresOldStrongDislikeAfterLogicalExpiryOrActualCacheLoss(boolean lost) {
        var f = new Fixture(); f.dislike("item");
        f.clock.hours(25);
        if (lost) f.preferences = new InMemoryOnlinePreferenceStore(f.clock);
        when(f.sessions.activeUntil("account","profile","session")).thenReturn(f.clock.origin.plus(Duration.ofHours(47)));
        var home = f.home();
        assertThat(home.recommendHome(ID,new HomeRecommendRequestDTO("session","home",1,"",false)).items()).isEmpty();
        assertThat(f.preferences.load(ID).itemPreferences().get("item").scope()).isEqualTo("session");
        var other = f.preferences.load(new RecommendationIdentity("account","profile","other-session"))
                .itemPreferences().get("item");
        if (lost) assertThat(other).isNull();
        else assertThat(other.scope()).isEqualTo("profile");
        verify(f.sessions,never()).requireActive(anyString(),anyString(),anyString());
    }

    @Test
    void authoritativeExpiryRenewalPreservesSameVersionItemsButDoesNotReviveDeletedItem() {
        var f = new Fixture(); var original = f.dislike("item");
        var reversal = f.events.append(new FeedbackAppendCommand("reverse",ID,original.item(),FeedbackEventType.REVERSAL,
                original.eventId(),f.clock.instant(),f.clock.instant(),null)).event();
        f.preferences.applyReversal(reversal,null,null);
        f.clock.hours(25);
        when(f.sessions.activeUntil("account","profile","session")).thenReturn(f.clock.origin.plus(Duration.ofHours(47)));
        f.reader().restore(ID);
        f.preferences.restoreSession(original,null,f.clock.origin.plus(Duration.ofHours(47)));
        assertThat(f.preferences.load(ID).itemPreferences()).doesNotContainKey("item");
        assertThat(f.preferences.load(ID).itemVersions().get("item")).isEqualTo(reversal.preferenceVersion());
    }

    @Test
    void backgroundRebuildUsesActiveUserSessionsEvenWhenFeedbackIsOlderThanTwentyFourHours() {
        var f = new Fixture(); var original = f.dislike("item"); f.clock.hours(25);
        f.preferences = new InMemoryOnlinePreferenceStore(f.clock);
        var expiry = f.clock.origin.plus(Duration.ofHours(47));
        when(f.sessions.activeSessions("",50)).thenReturn(List.of(new ActiveRecommendationSession(ID,expiry)));
        var worker = new FeedbackProjectionRetryWorker(f.events,f.preferences,mock(RecommendationFeedbackMetrics.class),f.clock);
        worker.setSessionPreferenceReader(f.reader()); worker.rebuildCurrentPreferences();
        var item = f.preferences.load(ID).itemPreferences().get("item");
        assertThat(item.scope()).isEqualTo("session");
        assertThat(item.eventId()).isEqualTo(original.eventId());
        verify(f.sessions,never()).requireActive(anyString(),anyString(),anyString());
    }

    @Test
    void backgroundRebuildResumesLargeSessionAndContinuesToOtherSessions() {
        var f = new Fixture();
        for (int i = 0; i < 1002; i++) f.dislike(String.format("item-%04d",i));
        var second = new RecommendationIdentity("account","profile","session-z");
        f.events.append(new FeedbackAppendCommand("other",second,
                new RecommendationDeliveryItem("other",1,1,"books","brand",Map.of()),FeedbackEventType.LIKE,
                null,f.clock.instant(),f.clock.instant()));
        f.preferences = new InMemoryOnlinePreferenceStore(f.clock);
        var expiry = f.clock.origin.plus(Duration.ofHours(47));
        when(f.sessions.activeSessions("",50)).thenReturn(List.of(new ActiveRecommendationSession(ID,expiry),new ActiveRecommendationSession(second,expiry)));
        when(f.sessions.activeSessions("session",50)).thenReturn(List.of(new ActiveRecommendationSession(second,expiry)));
        when(f.sessions.activeUntil("account","profile","session")).thenReturn(expiry);
        var worker = new FeedbackProjectionRetryWorker(f.events,f.preferences,mock(RecommendationFeedbackMetrics.class),f.clock);
        worker.setSessionPreferenceReader(f.reader()); worker.rebuildCurrentPreferences(); worker.rebuildCurrentPreferences();
        assertThat(f.preferences.load(ID).itemPreferences()).containsKey("item-1001");
        assertThat(f.preferences.load(second).itemPreferences().get("other").scope()).isEqualTo("session");
        verify(f.sessions).activeSessions("session",50);
    }

    @Test
    void endedOrUnavailableSessionFailsClosedBeforeRecommendationAndBackgroundDoesNotRenewIt() {
        var f = new Fixture(); f.dislike("item"); f.clock.hours(25);
        when(f.sessions.activeUntil("account","profile","session")).thenThrow(new ResponseStatusException(HttpStatus.GONE));
        assertThatThrownBy(() -> f.home().recommendHome(ID,new HomeRecommendRequestDTO("session","home",1,"",false)))
                .isInstanceOf(ResponseStatusException.class).hasMessageContaining("410");
        assertThat(f.reader().activeUntil(ID)).isEmpty();
        doThrow(new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE)).when(f.sessions).activeUntil("account","profile","session");
        assertThatThrownBy(() -> f.home().recommendHome(ID,new HomeRecommendRequestDTO("session","home",1,"",false)))
                .isInstanceOf(ResponseStatusException.class).hasMessageContaining("503");
    }

    @Test
    void outboxRetryRestoresOldFeedbackUsingCurrentActivityBeforeReportingApplied() {
        var f = new Fixture(); var original = f.dislike("item"); f.clock.hours(25);
        f.events.markProjectionFailed(original.eventId(),"缓存丢失");
        f.preferences = new InMemoryOnlinePreferenceStore(f.clock);
        when(f.sessions.activeUntil("account","profile","session")).thenReturn(f.clock.origin.plus(Duration.ofHours(47)));
        var worker = new FeedbackProjectionRetryWorker(f.events,f.preferences,mock(RecommendationFeedbackMetrics.class),f.clock);
        worker.setSessionPreferenceReader(f.reader()); worker.retryPending();
        assertThat(f.events.projectionStatus(original.eventId())).isEqualTo("APPLIED");
        assertThat(f.preferences.load(ID).itemPreferences().get("item").scope()).isEqualTo("session");
    }

    @ParameterizedTest
    @ValueSource(booleans = {false,true})
    void oneSessionReadOrProjectionFailureDoesNotBlockOthersAndIsRetriedNextScan(boolean readFailure) {
        var f = new Fixture(); f.dislike("item");
        var other = new RecommendationIdentity("account","profile","session-z");
        f.events.append(new FeedbackAppendCommand("other",other,
                new RecommendationDeliveryItem("other",1,1,"books","brand",Map.of()),FeedbackEventType.LIKE,
                null,f.clock.instant(),f.clock.instant()));
        var facts = spy(f.events);
        var cache = spy(new InMemoryOnlinePreferenceStore(f.clock));
        var expiry = f.clock.origin.plus(Duration.ofHours(47));
        when(f.sessions.activeSessions("",50)).thenReturn(List.of(new ActiveRecommendationSession(ID,expiry),new ActiveRecommendationSession(other,expiry)));
        if (readFailure) doThrow(new IllegalStateException("模拟单会话事实读取失败")).when(facts).currentSessionEvents(eq(ID),anyString(),anyInt());
        else doThrow(new IllegalStateException("模拟单会话投影失败")).when(cache).restoreSession(
                argThat(event -> event.identity().equals(ID)),nullable(RecommendationFeedbackEvent.class),any());
        var reader = new SessionPreferenceReader(facts,cache,f.sessions);
        var worker = new FeedbackProjectionRetryWorker(facts,cache,mock(RecommendationFeedbackMetrics.class),f.clock);
        worker.setSessionPreferenceReader(reader); worker.rebuildCurrentPreferences();
        assertThat(cache.load(other).itemPreferences().get("other").scope()).isEqualTo("session");
        if (readFailure) doCallRealMethod().when(facts).currentSessionEvents(eq(ID),anyString(),anyInt());
        else doCallRealMethod().when(cache).restoreSession(argThat(event -> event.identity().equals(ID)),nullable(RecommendationFeedbackEvent.class),any());
        worker.rebuildCurrentPreferences();
        assertThat(cache.load(ID).itemPreferences().get("item").scope()).isEqualTo("session");
    }

    static class Fixture {
        final MutableClock clock = new MutableClock();
        final InMemoryRecommendationFeedbackEventStore events = new InMemoryRecommendationFeedbackEventStore();
        final RecommendationSessionValidator sessions = mock(RecommendationSessionValidator.class);
        OnlinePreferenceStore preferences = new InMemoryOnlinePreferenceStore(clock);
        RecommendationFeedbackEvent dislike(String itemId) {
            var item = new RecommendationDeliveryItem(itemId,1,1,"books","brand",Map.of());
            var event = events.append(new FeedbackAppendCommand("delivery-"+itemId,ID,item,FeedbackEventType.DISLIKE,
                    null,clock.instant(),clock.instant())).event();
            preferences.apply(event); return event;
        }
        SessionPreferenceReader reader() { return new SessionPreferenceReader(events,preferences,sessions); }
        DefaultHomeRecommendService home() {
            var item = new ItemEmbeddingText("item","Book","Book","books","books","brand",BigDecimal.TEN,Map.of());
            var service = new DefaultHomeRecommendService(mock(RecommendTraceService.class),(cursor,limit) -> List.of(item),
                    new DefaultRecommendationDeliveryService(new InMemoryRecommendationDeliveryStore(),clock,Duration.ofHours(24)),
                    preferences,new PreferenceAwareFinalReranker(clock,30));
            service.setSessionPreferenceReader(reader()); return service;
        }
    }
}
