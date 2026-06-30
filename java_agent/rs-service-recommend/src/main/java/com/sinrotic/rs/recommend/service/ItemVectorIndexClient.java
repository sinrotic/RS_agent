package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.recall.ItemVectorDocument;

import java.util.List;

public interface ItemVectorIndexClient {

    int upsertItems(String collectionName, List<ItemVectorDocument> documents);
}
