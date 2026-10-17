package com.sinrotic.rs.agent.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.HashSet;

/** The shopping catalog is a deliberately small A2UI v0.9 subset, not the Basic Catalog. */
public final class A2uiMessageProjector {
    public static final String CATALOG_ID = "urn:rs-agent:a2ui:shopping:v1";
    private static final Set<String> OPERATIONS = Set.of(
            "createSurface", "updateComponents", "updateDataModel", "deleteSurface");
    private static final Set<String> UNSAFE_KEYS = Set.of("__proto__", "constructor", "prototype");
    private static final Set<String> INTERNAL_DATA_KEYS = Set.of("trace", "diagnostics", "raw_path",
            "ranking_evidence", "retrieval_evidence", "tool_calls", "tool_results", "system_prompt", "available_tools");
    private static final Map<String, Object> COMPONENTS = componentSchemas();

    /** Turn-local lifecycle validation; no UI state is shared between Sessions. */
    public static final class State {
        private Map<String, Map<String, Map<?, ?>>> surfaces = new LinkedHashMap<>();

        public State(Object previous) {
            if (previous == null) return;
            if (!(previous instanceof List<?> list) || list.size() > 8) {
                throw new IllegalArgumentException("invalid a2ui_state");
            }
            for (Object value : list) {
                Map<?, ?> surface = object(value);
                if (!(surface.get("surfaceId") instanceof String)
                        || !(surface.get("catalogId") instanceof String)
                        || !(surface.get("components") instanceof List<?>)) {
                    throw new IllegalArgumentException("invalid a2ui_state surface");
                }
                var messages = new ArrayList<Map<String, Object>>();
                messages.add(Map.of("version", "v0.9", "createSurface", Map.of(
                        "surfaceId", surface.get("surfaceId"), "catalogId", surface.get("catalogId"))));
                if (surface.get("components") instanceof List<?> components && !components.isEmpty()) {
                    messages.add(Map.of("version", "v0.9", "updateComponents", Map.of(
                            "surfaceId", surface.get("surfaceId"), "components", components)));
                }
                if (surface.containsKey("data")) {
                    Map<String, Object> dataUpdate = new LinkedHashMap<>();
                    dataUpdate.put("surfaceId", surface.get("surfaceId"));
                    dataUpdate.put("value", surface.get("data"));
                    messages.add(Map.of("version", "v0.9", "updateDataModel", dataUpdate));
                }
                new A2uiMessageProjector().project(messages);
                accept(messages);
            }
        }

        public void accept(Object rawMessages) {
            List<Map<String, Object>> messages = new A2uiMessageProjector().project(rawMessages);
            Map<String, Map<String, Map<?, ?>>> next = new LinkedHashMap<>();
            surfaces.forEach((id, components) -> next.put(id, new LinkedHashMap<>(components)));
            for (Map<String, Object> message : messages) {
                String operation = OPERATIONS.stream().filter(message::containsKey).findFirst().orElseThrow();
                Map<?, ?> payload = object(message.get(operation));
                String id = (String) payload.get("surfaceId");
                if ("createSurface".equals(operation)) {
                    if (next.containsKey(id) || next.size() >= 8) throw new IllegalArgumentException("A2UI surface already exists or limit reached");
                    next.put(id, new LinkedHashMap<>());
                } else {
                    if (!next.containsKey(id)) throw new IllegalArgumentException("A2UI surface must be created first");
                    if ("deleteSurface".equals(operation)) next.remove(id);
                    if ("updateComponents".equals(operation)) {
                        for (Object rawComponent : (List<?>) payload.get("components")) {
                            Map<?, ?> component = object(rawComponent);
                            next.get(id).put((String) component.get("id"), component);
                        }
                        if (next.get(id).size() > 64) throw new IllegalArgumentException("A2UI component limit reached");
                    }
                }
            }
            for (Map<String, Map<?, ?>> components : next.values()) {
                Set<String> visited = new HashSet<>();
                for (String id : components.keySet()) visit(id, components, visited, new HashSet<>());
            }
            surfaces = next;
        }

        public void validateComplete() {
            for (Map<String, Map<?, ?>> components : surfaces.values()) {
                if (!components.containsKey("root")) throw new IllegalArgumentException("A2UI surface requires root component");
                for (Map<?, ?> component : components.values()) {
                    if (component.get("child") instanceof String child && !components.containsKey(child)) {
                        throw new IllegalArgumentException("A2UI child component not found");
                    }
                    if (component.get("children") instanceof List<?> children
                            && children.stream().anyMatch(child -> !components.containsKey(child))) {
                        throw new IllegalArgumentException("A2UI child component not found");
                    }
                }
            }
        }

        private static void visit(String id, Map<String, Map<?, ?>> components, Set<String> visited, Set<String> active) {
            if (active.contains(id) || active.size() > 32) throw new IllegalArgumentException("A2UI component cycle or depth limit");
            if (visited.contains(id) || !components.containsKey(id)) return;
            active.add(id);
            Map<?, ?> component = components.get(id);
            if (component.get("child") instanceof String child) visit(child, components, visited, active);
            if (component.get("children") instanceof List<?> children) {
                for (Object child : children) visit((String) child, components, visited, active);
            }
            active.remove(id);
            visited.add(id);
        }
    }

    public List<Map<String, Object>> project(Object value) {
        if (!(value instanceof List<?> messages) || messages.isEmpty() || messages.size() > 32) {
            throw new IllegalArgumentException("A2UI requires 1..32 messages");
        }
        List<Map<String, Object>> result = new ArrayList<>();
        for (Object message : messages) {
            Map<?, ?> raw = object(message);
            if (!"v0.9".equals(raw.get("version"))) {
                throw new IllegalArgumentException("unsupported A2UI version");
            }
            List<String> operations = OPERATIONS.stream().filter(raw::containsKey).toList();
            if (operations.size() != 1 || raw.size() != 2) {
                throw new IllegalArgumentException("A2UI message requires exactly one operation");
            }
            String operation = operations.getFirst();
            Map<?, ?> payload = object(raw.get(operation));
            validate(payload, operationSchema(operation), 0);
            if ("updateDataModel".equals(operation) && payload.containsKey("value")) {
                validateJson(payload.get("value"), 0);
            }
            result.add(Map.of("version", "v0.9", operation, payload));
        }
        try {
            if (new ObjectMapper().writeValueAsBytes(result).length > 64_000) {
                throw new IllegalArgumentException("A2UI message batch exceeds 64000 bytes");
            }
        } catch (JsonProcessingException error) {
            throw new IllegalArgumentException("A2UI messages must be JSON", error);
        }
        return List.copyOf(result);
    }

    public static Map<String, Object> messagesSchema() {
        List<Map<String, Object>> variants = OPERATIONS.stream().sorted().map(operation -> objectSchema(
                Map.of("version", Map.of("const", "v0.9"), operation, operationSchema(operation)),
                List.of("version", operation))).toList();
        return Map.of("type", "array", "minItems", 1, "maxItems", 32,
                "items", Map.of("oneOf", variants));
    }

    public static String modelInstructions() {
        try {
            return "\n\n## 当前前端组件目录与消息 Schema\n"
                    + new ObjectMapper().writeValueAsString(Map.of(
                    "catalogId", CATALOG_ID, "components", COMPONENTS, "messages", messagesSchema()));
        } catch (JsonProcessingException error) {
            throw new IllegalStateException("cannot serialize A2UI schema", error);
        }
    }

    private static Map<String, Object> operationSchema(String operation) {
        Map<String, Object> props = new LinkedHashMap<>();
        props.put("surfaceId", identifier());
        return switch (operation) {
            case "createSurface" -> {
                props.put("catalogId", Map.of("const", CATALOG_ID));
                yield objectSchema(props, List.of("surfaceId", "catalogId"));
            }
            case "updateComponents" -> {
                List<Map<String, Object>> variants = new ArrayList<>();
                COMPONENTS.forEach((name, schema) -> {
                    Map<?, ?> definition = object(schema);
                    Map<String, Object> fields = new LinkedHashMap<>();
                    fields.put("id", identifier());
                    fields.put("component", Map.of("const", name));
                    object(definition.get("properties")).forEach((key, field) -> fields.put((String) key, field));
                    List<String> required = new ArrayList<>(List.of("id", "component"));
                    for (Object key : (List<?>) definition.get("required")) required.add((String) key);
                    variants.add(objectSchema(fields, required));
                });
                props.put("components", Map.of("type", "array", "minItems", 1, "maxItems", 64,
                        "items", Map.of("oneOf", variants)));
                yield objectSchema(props, List.of("surfaceId", "components"));
            }
            case "updateDataModel" -> {
                props.put("path", pointer());
                props.put("value", Map.of());
                yield objectSchema(props, List.of("surfaceId"));
            }
            case "deleteSurface" -> objectSchema(props, List.of("surfaceId"));
            default -> throw new IllegalArgumentException("unknown A2UI operation");
        };
    }

    private static Map<String, Object> componentSchemas() {
        Map<String, Object> result = new LinkedHashMap<>();
        Map<String, Object> children = Map.of("type", "array", "maxItems", 32, "items", identifier());
        result.put("Column", objectSchema(Map.of("children", children), List.of("children")));
        result.put("Row", objectSchema(Map.of("children", children), List.of("children")));
        result.put("Card", objectSchema(Map.of("child", identifier()), List.of("child")));
        result.put("Text", objectSchema(Map.of("text", boundText()), List.of("text")));
        result.put("ProductCards", objectSchema(Map.of(
                "itemIds", Map.of("type", "array", "maxItems", 20, "items", identifier()),
                "layout", Map.of("type", "string", "enum", List.of("grid", "list"))), List.of("itemIds")));
        result.put("TextField", objectSchema(Map.of(
                "label", text(), "value", objectSchema(Map.of("path", pointer()), List.of("path")),
                "textFieldType", Map.of("type", "string", "enum", List.of("shortText", "number"))),
                List.of("label", "value")));
        Map<String, Object> context = objectSchema(Map.of("query", boundText()), List.of("query"));
        Map<String, Object> event = objectSchema(Map.of(
                "name", Map.of("const", "submit_query"), "context", context), List.of("name", "context"));
        result.put("Button", objectSchema(Map.of("child", identifier(),
                "action", objectSchema(Map.of("event", event), List.of("event"))), List.of("child", "action")));
        return Map.copyOf(result);
    }

    private static Map<String, Object> objectSchema(Map<String, Object> properties, List<String> required) {
        return Map.of("type", "object", "properties", properties,
                "required", required, "additionalProperties", false);
    }

    private static Map<String, Object> text() {
        return Map.of("type", "string", "maxLength", 4000);
    }

    private static Map<String, Object> identifier() {
        return Map.of("type", "string", "minLength", 1, "maxLength", 128,
                "pattern", "^[A-Za-z0-9_:.-]+$");
    }

    private static Map<String, Object> pointer() {
        return Map.of("type", "string", "maxLength", 256, "pattern", "^(/([^~/]|~[01])*)*$");
    }

    private static Map<String, Object> boundText() {
        return Map.of("oneOf", List.of(text(), objectSchema(Map.of("path", pointer()), List.of("path"))));
    }

    private static Map<?, ?> object(Object value) {
        if (!(value instanceof Map<?, ?> map)) throw new IllegalArgumentException("A2UI expects an object");
        return map;
    }

    private static void validate(Object value, Map<?, ?> schema, int depth) {
        if (depth > 16) throw new IllegalArgumentException("A2UI exceeds maximum depth");
        if (schema.get("oneOf") instanceof List<?> variants) {
            int matches = 0;
            for (Object variant : variants) {
                try { validate(value, object(variant), depth + 1); matches++; }
                catch (IllegalArgumentException ignored) { }
            }
            if (matches != 1) throw new IllegalArgumentException("A2UI value does not match catalog schema");
            return;
        }
        if (schema.containsKey("const") && !schema.get("const").equals(value)) {
            throw new IllegalArgumentException("A2UI value does not match constant");
        }
        if (schema.get("enum") instanceof List<?> values && !values.contains(value)) {
            throw new IllegalArgumentException("unsupported A2UI catalog value");
        }
        if ("string".equals(schema.get("type"))) {
            if (!(value instanceof String text)) throw new IllegalArgumentException("A2UI expects a string");
            if (schema.get("minLength") instanceof Number min && text.length() < min.intValue()
                    || schema.get("maxLength") instanceof Number max && text.length() > max.intValue()
                    || schema.get("pattern") instanceof String pattern && !text.matches(pattern)) {
                throw new IllegalArgumentException("invalid A2UI string");
            }
            if (schema.equals(pointer())) validatePointer(text);
        }
        if ("array".equals(schema.get("type"))) {
            if (!(value instanceof List<?> list)) throw new IllegalArgumentException("A2UI expects an array");
            if (schema.get("minItems") instanceof Number min && list.size() < min.intValue()
                    || schema.get("maxItems") instanceof Number max && list.size() > max.intValue()) {
                throw new IllegalArgumentException("invalid A2UI array size");
            }
            for (Object item : list) validate(item, object(schema.get("items")), depth + 1);
        }
        if ("object".equals(schema.get("type"))) {
            Map<?, ?> map = object(value);
            Map<?, ?> properties = object(schema.get("properties"));
            for (Object required : (List<?>) schema.get("required")) {
                if (!map.containsKey(required)) throw new IllegalArgumentException("missing A2UI field: " + required);
            }
            map.forEach((key, item) -> {
                if (!properties.containsKey(key)) throw new IllegalArgumentException("unknown A2UI field: " + key);
                validate(item, object(properties.get(key)), depth + 1);
            });
        }
    }

    private static void validatePointer(String path) {
        for (String part : path.split("/", -1)) {
            String key = part.replace("~1", "/").replace("~0", "~");
            if (UNSAFE_KEYS.contains(key)) throw new IllegalArgumentException("unsafe A2UI data path");
        }
    }

    private static void validateJson(Object value, int depth) {
        if (depth > 8) throw new IllegalArgumentException("A2UI data exceeds maximum depth");
        if (value == null || value instanceof Boolean) return;
        if (value instanceof Number number && Double.isFinite(number.doubleValue())) return;
        if (value instanceof String text && text.length() <= 4000) return;
        if (value instanceof List<?> list && list.size() <= 64) {
            list.forEach(item -> validateJson(item, depth + 1));
            return;
        }
        if (value instanceof Map<?, ?> map && map.size() <= 64) {
            map.forEach((key, item) -> {
                if (!(key instanceof String text) || text.length() > 128 || UNSAFE_KEYS.contains(text)
                        || INTERNAL_DATA_KEYS.contains(text)) {
                    throw new IllegalArgumentException("invalid A2UI data key");
                }
                validateJson(item, depth + 1);
            });
            return;
        }
        throw new IllegalArgumentException("invalid A2UI data value");
    }
}
