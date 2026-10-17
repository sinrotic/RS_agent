package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.vo.PipelineCandidateVO;
import com.sinrotic.rs.recommend.service.impl.ProtectedHeadTwoTowerRecallProvider;
import com.sinrotic.rs.recommend.service.impl.DefaultTwoTowerRecallProvider;
import com.sinrotic.rs.recommend.service.impl.BoundedUserEmbeddingStore;
import com.sinrotic.rs.recommend.domain.recall.UserEmbedding;
import com.sinrotic.rs.recommend.domain.recall.VectorRecallItem;
import com.sinrotic.rs.recommend.config.TwoTowerRecallConfiguration;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.core.env.SystemEnvironmentPropertySource;
import org.springframework.web.client.RestClient;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import static org.junit.jupiter.api.Assertions.*;

class ProtectedHeadTwoTowerRecallProviderTest {
    private PipelineCandidateVO hit(String id, double score) {
        return new PipelineCandidateVO(id, "two_tower", score, null, null, null);
    }

    @Test void protectsHeadExcludesSeenAndDeduplicatesWithoutComparingDifferentSpaceScores() {
        TwoTowerRecallProvider main = (u,r,n) -> List.of(hit("seen",1),hit("new",.9),hit("old",.7),hit("other",.6));
        TwoTowerRecallProvider old = (u,r,n) -> List.of(hit("seen",1),hit("old",.1));
        var provider = new ProtectedHeadTwoTowerRecallProvider(main,old,(u,n)->List.of("seen"),1);
        assertEquals(List.of("old","new","other"),provider.recall("u","r",3).stream().map(PipelineCandidateVO::itemId).toList());
        assertEquals(List.of("old"),provider.recall("u","r",1).stream().map(PipelineCandidateVO::itemId).toList());
    }

    @Test void emptyColdStartAndFaultRemainVisibleToExistingFallback() {
        var calls = new AtomicInteger();
        TwoTowerRecallProvider empty = (u,r,n) -> List.of();
        TwoTowerRecallProvider fault = (u,r,n) -> { calls.incrementAndGet();throw new IllegalStateException("runtime down"); };
        var cold = new ProtectedHeadTwoTowerRecallProvider(empty,fault,(u,n)->List.of(),10);
        assertTrue(cold.recall("u","r",100).isEmpty());assertEquals(0,calls.get());
        var active = new ProtectedHeadTwoTowerRecallProvider((u,r,n)->List.of(hit("a",1)),fault,(u,n)->List.of(),10);
        assertThrows(IllegalStateException.class,()->active.recall("u","r",100));
        assertTrue(active.recall("","r",100).isEmpty());assertTrue(active.recall("u","r",0).isEmpty());
        assertThrows(IllegalArgumentException.class,()->new ProtectedHeadTwoTowerRecallProvider(empty,empty,(u,n)->List.of(),51));
    }

    @Test void environmentCreatesActualGuardAndUsesSeparateRuntimeAndCollection() throws Exception {
        var calls = new AtomicInteger();
        var primaryCalls = new AtomicInteger();
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        server.createContext("/internal/model/two-tower/user-embedding",exchange -> {
            calls.incrementAndGet();
            String payload = new String(exchange.getRequestBody().readAllBytes(),StandardCharsets.UTF_8);
            if (!payload.contains("legacy")) { exchange.sendResponseHeaders(400,-1);exchange.close();return; }
            byte[] bytes = "{\"model_key\":\"legacy\",\"embedding\":[1,0]}".getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type","application/json");
            exchange.sendResponseHeaders(200,bytes.length);exchange.getResponseBody().write(bytes);exchange.close();
        });
        server.createContext("/main/internal/model/two-tower/user-embedding",exchange -> {
            primaryCalls.incrementAndGet();
            String payload = new String(exchange.getRequestBody().readAllBytes(),StandardCharsets.UTF_8);
            if (!payload.contains("main")) { exchange.sendResponseHeaders(400,-1);exchange.close();return; }
            byte[] bytes = "{\"model_key\":\"main\",\"embedding\":[0,1]}".getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type","application/json");
            exchange.sendResponseHeaders(200,bytes.length);exchange.getResponseBody().write(bytes);exchange.close();
        });
        server.start();
        try {
            var seenCollections = new ArrayList<String>();
            VectorRecallClient vectorClient = (collection,vector,limit) -> {
                seenCollections.add(collection);
                if (collection.equals("expanded")) {
                    assertEquals(List.of(0f,1f),vector);
                    return List.of(new VectorRecallItem("new",.9),new VectorRecallItem("old",.8));
                }
                assertEquals("previous",collection);assertEquals(List.of(1f,0f),vector);
                return List.of(new VectorRecallItem("old",.1));
            };
            UserTowerModelClient mainModel = (m,r,u,h) -> Optional.of(new UserEmbedding(m,u,List.of(0f,1f),"test"));
            new ApplicationContextRunner().withUserConfiguration(TwoTowerRecallConfiguration.class)
                    .withBean(RestClient.Builder.class,RestClient::builder)
                    .withBean(UserHistoryClient.class,()->(u,n)->List.of("seen1","seen2"))
                    .withBean(VectorRecallClient.class,()->vectorClient)
                    .withInitializer(context->context.getEnvironment().getPropertySources().addFirst(new SystemEnvironmentPropertySource("container",Map.of(
                            "RS_RECOMMEND_TWO_TOWER_PROTECTED_HEAD_COUNT","1",
                            "RS_RECOMMEND_TWO_TOWER_PROTECTED_BASE_URL","http://127.0.0.1:"+server.getAddress().getPort(),
                            "RS_RECOMMEND_TWO_TOWER_PROTECTED_MODEL_KEY","legacy",
                            "RS_RECOMMEND_TWO_TOWER_PROTECTED_COLLECTION","previous",
                            "RS_RECOMMEND_TWO_TOWER_PROTECTED_DIMENSION","2"))))
                    .withPropertyValues("rs.recommend.two-tower.enabled=true","rs.recommend.two-tower.model-key=main","rs.recommend.two-tower.collection=expanded",
                            "rs.recommend.two-tower.dimension=2","rs.recommend.two-tower.base-url=http://127.0.0.1:"+server.getAddress().getPort()+"/main")
                    .run(context->{
                        assertNull(context.getStartupFailure());
                        var provider=context.getBean(TwoTowerRecallProvider.class);
                        assertInstanceOf(ProtectedHeadTwoTowerRecallProvider.class,provider);
                        assertEquals(List.of("old","new"),provider.recall("u","r",2).stream().map(PipelineCandidateVO::itemId).toList());
                    });
            assertEquals(List.of("expanded","previous"),seenCollections);assertEquals(1,calls.get());assertEquals(1,primaryCalls.get());
            var factory = new TwoTowerRecallConfiguration();
            assertInstanceOf(DefaultTwoTowerRecallProvider.class,factory.twoTowerRecallProvider(new BoundedUserEmbeddingStore(),(u,n)->List.of(),mainModel,
                    vectorClient,RestClient.builder(),"main","expanded",0,"http://localhost","legacy","previous",2,false));
        } finally { server.stop(0); }
    }
}
