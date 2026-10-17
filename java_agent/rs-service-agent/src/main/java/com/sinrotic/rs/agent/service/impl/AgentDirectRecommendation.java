package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.config.AgentDirectRecommendationProperties;
import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.service.AgentRecommendationDelivery;
import com.sinrotic.rs.agent.service.AgentRuntimeConfigurationService;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.regex.Pattern;

/** Conservative first-Turn shortcut. All unsupported input stays on the Agent path. */
@Component
public final class AgentDirectRecommendation {
    private static final Pattern REQUEST = Pattern.compile(
            "^(?:请)?(?:给我|帮我)?推荐(?:一些|几款|一个)?(?:([0-9]{1,6}(?:\\.[0-9]{1,2})?)(元|美元)(?:以内|以下)的?)?(双肩包|耳机|键盘|鼠标|笔记本电脑)[。！!]?$"
    );
    private static final Map<String, Pattern> CATEGORIES = Map.of(
            "双肩包", Pattern.compile("双肩包|(?<![a-z])backpacks?(?![a-z])"),
            "耳机", Pattern.compile("耳机|(?<![a-z])(?:headphones?|earbuds?|earphones?)(?![a-z])"),
            "键盘", Pattern.compile("键盘|(?<![a-z])keyboards?(?![a-z])"),
            "鼠标", Pattern.compile("鼠标|(?<![a-z])(?:mice|mouse)(?![a-z])"),
            "笔记本电脑", Pattern.compile("笔记本电脑|(?<![a-z])(?:laptops?|notebook computers?)(?![a-z])")
    );
    private static final Set<String> CONTEXT_KEYS = Set.of("scene", "client_turn_id", "a2ui_state",
            "authenticated_account_id", "authenticated_profile_user_id");
    private final AgentDirectRecommendationProperties properties;
    private final AgentRuntimeConfigurationService runtime;
    private final InMemoryAgentRuntimeConfigurationService builtIn = new InMemoryAgentRuntimeConfigurationService();

    public AgentDirectRecommendation(AgentDirectRecommendationProperties properties,
                                     AgentRuntimeConfigurationService runtime) {
        this.properties = properties;
        this.runtime = runtime;
    }

    public boolean enabled() { return properties.isEnabled() || properties.isLlmSynthesisEnabled(); }

    public Optional<Plan> prepare(AgentChatRequestDTO request, boolean firstTurn, boolean hooksSupported) {
        if (!enabled() || !firstTurn || !hooksSupported || !compatibleRuntime()
                || request.userMessage() == null || request.resolvedLimit() > 20
                || !CONTEXT_KEYS.containsAll(request.resolvedContext().keySet())) return Optional.empty();
        Object ui = request.resolvedContext().get("a2ui_state");
        if (ui != null && !(ui instanceof Map<?, ?> state && state.isEmpty())
                && !(ui instanceof List<?> state && state.isEmpty())) return Optional.empty();
        var matcher = REQUEST.matcher(request.userMessage().trim());
        if (!matcher.matches()) return Optional.empty();
        BigDecimal maximum = matcher.group(1) == null ? null : new BigDecimal(matcher.group(1));
        String currency = matcher.group(2) == null ? "" : "美元".equals(matcher.group(2)) ? "USD" : "CNY";
        if (maximum != null && (maximum.signum() <= 0 || !currency.equals(properties.getCatalogCurrency())))
            return Optional.empty();
        var context = new LinkedHashMap<String, Object>(request.resolvedContext());
        if (maximum != null) context.put("constraints", Map.of("price_max", maximum));
        return Optional.of(new Plan(new AgentChatRequestDTO(request.sessionId(), request.profileUserId(),
                request.userMessage(), request.limit(), Map.copyOf(context)), matcher.group(3), maximum, currency));
    }

    public Optional<Map<String, Object>> answer(Plan plan, AgentRecommendationDelivery delivery) {
        if (!properties.isEnabled() || properties.isLlmSynthesisEnabled()) return Optional.empty();
        return validatedAnswer(plan, delivery);
    }

    public Optional<Map<String, Object>> synthesisContext(Plan plan, AgentRecommendationDelivery delivery) {
        if (!properties.isLlmSynthesisEnabled() || validatedAnswer(plan, delivery).isEmpty()) return Optional.empty();
        var context = new LinkedHashMap<String, Object>();
        context.put("final_answer_only", true);
        context.put("recommendation_synthesis_only", true);
        var skill = runtime.skill("explicit-need-recommendation");
        context.put("server_loaded_skills", List.of(Map.of("name", skill.name(), "content", skill.content())));
        var workflow = new LinkedHashMap<String, Object>();
        workflow.put("category", plan.category());
        workflow.put("item_ids", delivery.items().stream().map(item -> item.itemId()).toList());
        workflow.put("candidate_recall_and_ranking_completed", true);
        workflow.put("catalog_category_and_budget_validated", true);
        if (plan.maximum() != null) {
            workflow.put("price_max", plan.maximum());
            workflow.put("currency", plan.currency());
            workflow.put("prices", delivery.items().stream().collect(java.util.stream.Collectors.toMap(
                    item -> item.itemId(), item -> delivery.facts().get(item.itemId()).price())));
        }
        context.put("completed_recommendation_workflow", Map.copyOf(workflow));
        return Optional.of(Map.copyOf(context));
    }

    private Optional<Map<String, Object>> validatedAnswer(Plan plan, AgentRecommendationDelivery delivery) {
        if (!compatibleRuntime() || delivery.degraded()
                || delivery.items().isEmpty() || delivery.items().size() > 20) return Optional.empty();
        if (plan.maximum() != null && !plan.currency().equals(properties.getCatalogCurrency())) return Optional.empty();
        String cardSetId = delivery.items().getFirst().cardSetId();
        if (cardSetId == null || cardSetId.isBlank()) return Optional.empty();
        var ids = new java.util.HashSet<String>();
        var text = new StringBuilder("为你找到以下").append(plan.category()).append("：");
        int index = 0;
        for (var item : delivery.items()) {
            if (item.itemId() == null || item.itemId().isBlank() || !ids.add(item.itemId())
                    || !cardSetId.equals(item.cardSetId()) || item.title() == null || item.title().isBlank()
                    || item.title().length() > 512 || item.category() == null
                    || !matchesCategory(plan.category(), item.category()))
                return Optional.empty();
            text.append("\n").append(++index).append(". ").append(item.title()).append("：属于")
                    .append(plan.category()).append("类目");
            if (plan.maximum() != null) {
                var fact = delivery.facts().get(item.itemId());
                if (fact == null || fact.price() == null || fact.price().signum() < 0
                        || fact.price().compareTo(plan.maximum()) > 0) return Optional.empty();
                text.append("，价格 ").append(fact.price().stripTrailingZeros().toPlainString())
                        .append(" ").append(plan.currency()).append("，在预算内");
            }
            text.append("。");
        }
        return Optional.of(Map.of("blocks", List.of(
                Map.of("type", "text", "content", text.toString()),
                Map.of("type", "product_cards", "card_set_id", cardSetId,
                        "item_ids", delivery.items().stream().map(item -> item.itemId()).toList()))));
    }

    private boolean compatibleRuntime() {
        return runtime.defaultProfile().equals(builtIn.defaultProfile())
                && runtime.systemPrompt().equals(builtIn.systemPrompt())
                && runtime.skills().equals(builtIn.skills())
                && runtime.runtimeContextMessages().equals(builtIn.runtimeContextMessages())
                && runtime.toolsForProfile(runtime.defaultProfile()).equals(builtIn.toolsForProfile(builtIn.defaultProfile()));
    }

    private boolean matchesCategory(String requested, String actual) {
        // A parent category does not prove that a leaf product is not an accessory.
        String[] path = actual.toLowerCase(Locale.ROOT).split("[>/]");
        return path.length > 0 && CATEGORIES.get(requested).matcher(path[path.length - 1].trim()).matches();
    }

    public record Plan(AgentChatRequestDTO request, String category, BigDecimal maximum, String currency) { }
}
