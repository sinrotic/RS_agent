package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.vo.SemanticItemIndexResultVO;

public interface SemanticItemIndexService {

    SemanticItemIndexResultVO rebuild(String requestId, int pageSize, int maxPages);
}
