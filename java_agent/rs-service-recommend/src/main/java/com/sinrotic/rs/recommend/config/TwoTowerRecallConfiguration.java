package com.sinrotic.rs.recommend.config;

import com.sinrotic.rs.recommend.service.*;
import com.sinrotic.rs.recommend.service.impl.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestClient;

@Configuration
@ConditionalOnProperty(name = "rs.recommend.two-tower.enabled", havingValue = "true")
public class TwoTowerRecallConfiguration {
    @Bean public UserEmbeddingStore userEmbeddingStore() { return new BoundedUserEmbeddingStore(); }
    @Bean public UserTowerModelClient userTowerModelClient(RestClient.Builder builder,
            @Value("${rs.recommend.two-tower.base-url:http://172.21.0.1:18117}") String url,
            @Value("${rs.recommend.two-tower.dimension:64}") int dimension) {
        return new RestUserTowerModelClient(builder, url, dimension);
    }
    @Bean public TwoTowerRecallProvider twoTowerRecallProvider(UserEmbeddingStore store, UserHistoryClient history,
            UserTowerModelClient model, VectorRecallClient vectors,
            RestClient.Builder builder,
            @Value("${rs.recommend.two-tower.model-key:two_tower_sparse_aware_epoch5_queryv2}") String modelKey,
            @Value("${rs.recommend.two-tower.collection:rs_agent_two_tower_epoch5_20260913}") String collection,
            @Value("${rs.recommend.two-tower.protected-head-count:0}") int protectedHeadCount,
            @Value("${rs.recommend.two-tower.protected-base-url:http://172.21.0.1:18120}") String protectedBaseUrl,
            @Value("${rs.recommend.two-tower.protected-model-key:product_three_tower_v4_seed42_step6000}") String protectedModelKey,
            @Value("${rs.recommend.two-tower.protected-collection:rs_agent_product_three_tower_v4_20261011}") String protectedCollection,
            @Value("${rs.recommend.two-tower.protected-dimension:1024}") int protectedDimension,
            @Value("${rs.recommend.two-tower.filter-history:false}") boolean filterHistory) {
        var primary = new DefaultTwoTowerRecallProvider(store, history, model, vectors, modelKey, collection);
        if (protectedHeadCount == 0)
            return filterHistory ? new HistoryFilteredTwoTowerRecallProvider(primary,history) : primary;
        if (modelKey.equals(protectedModelKey) || collection.equals(protectedCollection))
            throw new IllegalArgumentException("protected route must use a separate model and collection");
        var protectedModel = new RestUserTowerModelClient(builder.clone(), protectedBaseUrl, protectedDimension);
        var legacy = new DefaultTwoTowerRecallProvider(store, history, protectedModel, vectors, protectedModelKey, protectedCollection);
        return new ProtectedHeadTwoTowerRecallProvider(primary, legacy, history, protectedHeadCount);
    }
}
