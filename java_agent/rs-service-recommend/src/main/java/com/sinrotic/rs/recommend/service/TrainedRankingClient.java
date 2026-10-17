package com.sinrotic.rs.recommend.service;

import java.util.List;

public interface TrainedRankingClient {
    Result rank(String profileUserId, List<String> itemIds, List<String> protectedIds, String stage, int coarseLimit, int fineLimit);
    record Item(String itemId, double coldScore, Double deepfmLogit, double score) { }
    record Result(List<Item> items, int inputCount, int coarseCount, int fineCount) { }
}
