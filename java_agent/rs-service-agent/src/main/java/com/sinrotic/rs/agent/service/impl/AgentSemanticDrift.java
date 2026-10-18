package com.sinrotic.rs.agent.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.*;

/** 规则只选择复核时机，语义结论来自复核器；UNKNOWN 与未复核不算 ALIGNED。 */
public final class AgentSemanticDrift {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final Map<String,List<String>> CATEGORIES = Map.of(
            "bag",List.of("背包","双肩包","backpack"), "tent",List.of("帐篷","tent"),
            "shoe",List.of("跑鞋","运动鞋","sneaker"), "keyboard",List.of("键盘","keyboard"),
            "phone",List.of("手机","smartphone"), "laptop",List.of("笔记本电脑","laptop"));
    @FunctionalInterface public interface Reviewer { Review review(String goal, List<String> recent, String query, AgentInterruptContext context); }
    public record Review(String status, String reason) {
        public Review {
            if (!Set.of("ALIGNED","DRIFT","UNKNOWN").contains(status)) throw new IllegalArgumentException("Invalid review status");
        }
        public static Review unknown(String reason) { return new Review("UNKNOWN",reason); }
    }
    public record Decision(boolean blocked, boolean finalAnswerOnly, String status, String reason, String signal) {
        public Map<String,Object> result() { return Map.of("status","FAILED","error_code",status.equals("DRIFT") ? "TOOL_SEMANTIC_DRIFT" : "TOOL_DRIFT_NOT_REVIEWED",
                "error_message","Revise the query to support the current user goal, or answer from verified evidence",
                "drift",Map.of("review_status",status,"reason",reason,"signal",signal,"final_answer_only",finalAnswerOnly)); }
    }
    public static Review parse(String response, String query) {
        try {
            var root = JSON.readTree(response);
            var keys = new HashSet<String>(); root.fieldNames().forEachRemaining(keys::add);
            if (!keys.equals(Set.of("decision","query","reason")) || !root.path("decision").isTextual()
                    || !root.path("query").isTextual() || !root.path("reason").isTextual() || !root.path("query").asText().equals(query)) return Review.unknown("invalid_response");
            String status = root.path("decision").asText(), reason = root.path("reason").asText();
            return switch (status + ":" + reason) {
                case "ALIGNED:supports_goal" -> new Review("ALIGNED",reason);
                case "DRIFT:unrelated_goal" -> new Review("DRIFT",reason);
                case "UNKNOWN:insufficient_context" -> Review.unknown(reason);
                default -> Review.unknown("invalid_response");
            };
        } catch (Exception invalid) { return Review.unknown("invalid_response"); }
    }
    public static String query(AgentModelStreamEvent tool) {
        if (!(tool.toolName().startsWith("recommend_") || Set.of("rag_support","rag_evidence_search","call_agent").contains(tool.toolName()))) return "";
        Object query = tool.arguments().getOrDefault("query",tool.arguments().getOrDefault("user_query",tool.arguments().get("task")));
        return query instanceof String text ? text.strip() : "";
    }
    public static String signal(String goal, String query) {
        var expected = categories(goal,true); var actual = categories(query,false);
        return !expected.isEmpty() && !actual.isEmpty() && Collections.disjoint(expected,actual) ? "category_switch" : "periodic";
    }
    private static Set<String> categories(String text, boolean removeNegation) {
        String lower = text.toLowerCase(Locale.ROOT); var result = new HashSet<String>();
        CATEGORIES.forEach((category, words) -> {
            for (String word : words) {
                int from = 0, found;
                while ((found = lower.indexOf(word,from)) >= 0) {
                    String prefix = lower.substring(Math.max(0,found-10),found);
                    prefix = prefix.replaceAll("(?s).*[,，;；。!?！？]", "");
                    if (!removeNegation || !prefix.matches("(?s).*(?:不要|不需要|排除|别|不是|not |no |without ).{0,4}")) { result.add(category); break; }
                    from = found + word.length();
                }
            }
        }); return result;
    }
}
