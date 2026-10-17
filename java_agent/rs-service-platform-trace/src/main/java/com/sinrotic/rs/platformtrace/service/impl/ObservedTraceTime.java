package com.sinrotic.rs.platformtrace.service.impl;

import com.sinrotic.rs.platformtrace.domain.vo.AgentRunEventVO;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/** 合并有测量值的时间区间；父子或并行事件不重复累计，未覆盖的间隙不推断。 */
final class ObservedTraceTime {
    static long milliseconds(List<AgentRunEventVO> events) {
        var ranges = new ArrayList<Range>();
        for (var event : events) {
            if (event.latencyMs() == null || event.latencyMs() < 0) continue;
            try { ranges.add(new Range(event.createdAt().minusMillis(event.latencyMs()), event.createdAt())); }
            catch (RuntimeException invalidTimestamp) { /* 不把坏点位伪造成耗时。 */ }
        }
        ranges.sort(Comparator.comparing(Range::start));
        if (ranges.isEmpty()) return 0;
        Instant start = ranges.getFirst().start(), end = ranges.getFirst().end();
        long total = 0;
        for (var range : ranges.subList(1, ranges.size())) {
            if (range.start().isAfter(end)) {
                total = Math.addExact(total, Duration.between(start, end).toMillis());
                start = range.start(); end = range.end();
            } else if (range.end().isAfter(end)) end = range.end();
        }
        return Math.addExact(total, Duration.between(start, end).toMillis());
    }
    private record Range(Instant start, Instant end) { }
}
