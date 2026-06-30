package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.config.AgentToolResultStoreProperties;
import com.sinrotic.rs.agent.domain.session.AgentToolResultLines;
import com.sinrotic.rs.agent.service.impl.RedisAgentToolResultStore;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.HashOperations;
import org.springframework.data.redis.core.ListOperations;
import org.springframework.data.redis.core.StringRedisTemplate;

import java.time.Duration;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class RedisAgentToolResultStoreTest {

    @Test
    void saveLinesStoresOriginalResultLinesAsRedisBlocksWithMeta() {
        StringRedisTemplate redisTemplate = mock(StringRedisTemplate.class);
        ListOperations<String, String> listOperations = mock(ListOperations.class);
        HashOperations<String, Object, Object> hashOperations = mock(HashOperations.class);
        when(redisTemplate.opsForList()).thenReturn(listOperations);
        when(redisTemplate.opsForHash()).thenReturn(hashOperations);
        AgentToolResultStoreProperties properties = properties(2, Duration.ofMinutes(30));
        RedisAgentToolResultStore store = new RedisAgentToolResultStore(redisTemplate, properties);

        store.saveLines("agent:result:sess_001:toolu_001", List.of("line-0", "line-1", "line-2", "line-3", "line-4"));

        verify(redisTemplate).delete("agent:result:sess_001:toolu_001:lines");
        verify(redisTemplate).delete("agent:result:sess_001:toolu_001:meta");
        verify(listOperations).rightPushAll(
                "agent:result:sess_001:toolu_001:lines",
                List.of("line-0\nline-1", "line-2\nline-3", "line-4")
        );
        verify(hashOperations).putAll(eq("agent:result:sess_001:toolu_001:meta"), argThat(meta ->
                "5".equals(meta.get("total_lines"))
                        && "2".equals(meta.get("block_line_count"))
                        && "1800".equals(meta.get("ttl_seconds"))
                        && meta.containsKey("created_at")
        ));
        verify(redisTemplate).expire("agent:result:sess_001:toolu_001:lines", Duration.ofMinutes(30));
        verify(redisTemplate).expire("agent:result:sess_001:toolu_001:meta", Duration.ofMinutes(30));
    }

    @Test
    void readLinesFetchesOnlyNeededRedisBlocksAndReturnsRequestedRange() {
        StringRedisTemplate redisTemplate = mock(StringRedisTemplate.class);
        ListOperations<String, String> listOperations = mock(ListOperations.class);
        HashOperations<String, Object, Object> hashOperations = mock(HashOperations.class);
        when(redisTemplate.opsForList()).thenReturn(listOperations);
        when(redisTemplate.opsForHash()).thenReturn(hashOperations);
        when(hashOperations.entries("agent:result:sess_001:toolu_001:meta")).thenReturn(Map.of(
                "total_lines", "5",
                "block_line_count", "2"
        ));
        when(listOperations.range("agent:result:sess_001:toolu_001:lines", 0, 1))
                .thenReturn(List.of("line-0\nline-1", "line-2\nline-3"));
        RedisAgentToolResultStore store = new RedisAgentToolResultStore(redisTemplate, properties(2, Duration.ofMinutes(30)));

        AgentToolResultLines result = store.readLines("agent:result:sess_001:toolu_001", 1, 3);

        assertThat(result.resultRef()).isEqualTo("agent:result:sess_001:toolu_001");
        assertThat(result.offset()).isEqualTo(1);
        assertThat(result.limit()).isEqualTo(3);
        assertThat(result.totalLines()).isEqualTo(5);
        assertThat(result.hasMore()).isTrue();
        assertThat(result.lines()).containsExactly("line-1", "line-2", "line-3");
        verify(listOperations).range("agent:result:sess_001:toolu_001:lines", 0, 1);
    }

    @Test
    void readLinesPreservesSingleEmptyLineBlock() {
        StringRedisTemplate redisTemplate = mock(StringRedisTemplate.class);
        ListOperations<String, String> listOperations = mock(ListOperations.class);
        HashOperations<String, Object, Object> hashOperations = mock(HashOperations.class);
        when(redisTemplate.opsForList()).thenReturn(listOperations);
        when(redisTemplate.opsForHash()).thenReturn(hashOperations);
        when(hashOperations.entries("agent:result:sess_001:toolu_empty:meta")).thenReturn(Map.of(
                "total_lines", "3",
                "block_line_count", "1"
        ));
        when(listOperations.range("agent:result:sess_001:toolu_empty:lines", 0, 2))
                .thenReturn(List.of("line-0", "", "line-2"));
        RedisAgentToolResultStore store = new RedisAgentToolResultStore(redisTemplate, properties(1, Duration.ofMinutes(30)));

        AgentToolResultLines result = store.readLines("agent:result:sess_001:toolu_empty", 0, 3);

        assertThat(result.lines()).containsExactly("line-0", "", "line-2");
    }

    private AgentToolResultStoreProperties properties(int blockLineCount, Duration ttl) {
        AgentToolResultStoreProperties properties = new AgentToolResultStoreProperties();
        properties.setBlockLineCount(blockLineCount);
        properties.setTtl(ttl);
        return properties;
    }
}
