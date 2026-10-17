package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.vo.PipelineCandidateVO;
import com.sinrotic.rs.recommend.service.impl.HistoryFilteredTwoTowerRecallProvider;
import com.sinrotic.rs.recommend.config.TwoTowerRecallConfiguration;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.core.env.SystemEnvironmentPropertySource;
import org.springframework.web.client.RestClient;
import org.junit.jupiter.api.Test;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import static org.junit.jupiter.api.Assertions.*;

class HistoryFilteredTwoTowerRecallProviderTest {
    private PipelineCandidateVO hit(String id) { return new PipelineCandidateVO(id,"two_tower",.8,null,null,null); }

    @Test void singleModelKeepsOrderMasksHistoryAndDoesNotReserveHead() {
        var calls=new AtomicInteger();
        TwoTowerRecallProvider model=(u,r,n)->{ calls.incrementAndGet();assertEquals(4,n);return List.of(hit("seen"),hit("a"),hit("a"),hit("b"),hit("c")); };
        var p=new HistoryFilteredTwoTowerRecallProvider(model,(u,n)->List.of("seen"));
        assertEquals(List.of("a","b","c"),p.recall("u","r",3).stream().map(PipelineCandidateVO::itemId).toList());
        assertEquals(1,calls.get());assertTrue(p.recall("","r",3).isEmpty());assertTrue(p.recall("u","r",0).isEmpty());
        assertEquals(1,calls.get());
        var broken=new HistoryFilteredTwoTowerRecallProvider((u,r,n)->{throw new IllegalStateException("model down");},(u,n)->List.of());
        assertThrows(IllegalStateException.class,()->broken.recall("u","r",3));
    }

    @Test void environmentSelectsSingleModelEvenWithUnreachableProtectedAddress() {
        new ApplicationContextRunner().withUserConfiguration(TwoTowerRecallConfiguration.class)
                .withBean(RestClient.Builder.class,RestClient::builder)
                .withBean(UserHistoryClient.class,()->(u,n)->List.of("seen1","seen2"))
                .withBean(VectorRecallClient.class,()->(c,v,n)->List.of())
                .withPropertyValues("rs.recommend.two-tower.enabled=true")
                .withInitializer(c->c.getEnvironment().getPropertySources().addFirst(new SystemEnvironmentPropertySource("container",Map.of(
                        "RS_RECOMMEND_TWO_TOWER_PROTECTED_HEAD_COUNT","0","RS_RECOMMEND_TWO_TOWER_FILTER_HISTORY","true",
                        "RS_RECOMMEND_TWO_TOWER_PROTECTED_BASE_URL","http://127.0.0.1:1"))))
                .run(c->{ assertNull(c.getStartupFailure());assertInstanceOf(HistoryFilteredTwoTowerRecallProvider.class,c.getBean(TwoTowerRecallProvider.class)); });
    }
}
