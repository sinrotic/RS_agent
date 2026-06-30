package com.sinrotic.rs.recommend.service;

import java.util.List;

public interface TextEmbeddingClient {

    List<List<Float>> embedTexts(String modelKey, String requestId, List<String> texts);
}
