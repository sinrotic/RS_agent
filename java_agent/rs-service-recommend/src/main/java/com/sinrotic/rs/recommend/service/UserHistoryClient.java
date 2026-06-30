package com.sinrotic.rs.recommend.service;

import java.util.List;

/**
 * Provides recent valid item ids for user-tower inference.
 */
public interface UserHistoryClient {

    List<String> recentItemIds(String userId, int limit);
}
