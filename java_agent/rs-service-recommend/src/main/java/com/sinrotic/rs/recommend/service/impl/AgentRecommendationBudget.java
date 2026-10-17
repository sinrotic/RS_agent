package com.sinrotic.rs.recommend.service.impl;

import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
import java.math.BigDecimal;
import java.util.Map;

/** Agent 各成功及降级路径共用价格约束；有预算时，未知价格不能证明满足约束。 */
record AgentRecommendationBudget(BigDecimal min, BigDecimal max) {
    static AgentRecommendationBudget from(Map<String,Object> constraints) {
        var budget = new AgentRecommendationBudget(number(constraints,"price_min","min_price","budget_min"),
                number(constraints,"price_max","max_price","budget_max","budget"));
        if (budget.min!=null && budget.min.signum()<0 || budget.max!=null && budget.max.signum()<0
                || budget.min!=null && budget.max!=null && budget.min.compareTo(budget.max)>0)
            throw invalid();
        return budget;
    }
    boolean matches(BigDecimal price) {
        if (min==null && max==null) return true;
        return price!=null && (min==null || price.compareTo(min)>=0) && (max==null || price.compareTo(max)<=0);
    }
    private static BigDecimal number(Map<String,Object> constraints,String... keys) {
        if (constraints==null) return null;
        for (String key:keys) if (constraints.get(key)!=null) {
            try { return new BigDecimal(constraints.get(key).toString()); }
            catch (NumberFormatException error) { throw invalid(); }
        }
        return null;
    }
    private static ResponseStatusException invalid() {
        return new ResponseStatusException(HttpStatus.BAD_REQUEST,"价格约束无效");
    }
}
