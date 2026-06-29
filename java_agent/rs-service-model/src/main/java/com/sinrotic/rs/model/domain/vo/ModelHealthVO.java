package com.sinrotic.rs.model.domain.vo;

import java.util.List;
import java.util.Map;

public record ModelHealthVO(
        String status,
        Map<String, Object> manifest,
        List<Map<String, Object>> runtimes
) {
}
