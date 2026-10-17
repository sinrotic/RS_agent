package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.recall.UserEmbedding;
import com.sinrotic.rs.recommend.service.UserEmbeddingStore;
import java.time.Clock;
import java.util.*;

public final class BoundedUserEmbeddingStore implements UserEmbeddingStore {
    private record Key(String model, String user, List<String> history) { }
    private record Entry(UserEmbedding embedding, long expiresAt) { }
    private final Map<Key, Entry> cache = new LinkedHashMap<>(128, .75f, true);
    private final Clock clock;
    public BoundedUserEmbeddingStore() { this(Clock.systemUTC()); }
    public BoundedUserEmbeddingStore(Clock clock) { this.clock = clock; }
    public Optional<UserEmbedding> find(String model, String user) { return find(model, user, List.of()); }
    public void save(UserEmbedding embedding) { save(embedding, List.of()); }
    public synchronized Optional<UserEmbedding> find(String model, String user, List<String> history) {
        var key = new Key(model, user, List.copyOf(history));
        var entry = cache.get(key);
        if (entry == null) return Optional.empty();
        if (entry.expiresAt() <= clock.millis()) { cache.remove(key); return Optional.empty(); }
        return Optional.of(entry.embedding());
    }
    public synchronized void save(UserEmbedding embedding, List<String> history) {
        cache.put(new Key(embedding.modelName(), embedding.userId(), List.copyOf(history)), new Entry(embedding, clock.millis() + 600_000));
        while (cache.size() > 5000) cache.remove(cache.keySet().iterator().next());
    }
}
