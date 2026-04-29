from rs_core.simulation import (
    COMMUTER_PRACTICAL,
    GIFT_BUYER,
    PRICE_SENSITIVE,
    PRESET_ROLES,
    RoleActionType,
    RolePolicy,
    RoleState,
    get_preset_role,
)


def test_role_initial_prompt_includes_goal_and_preferences():
    prompt = COMMUTER_PRACTICAL.initial_prompt()

    assert "daily commute" in prompt
    assert "Prefer categories: Audio" in prompt
    assert "bluetooth" in prompt
    assert "Avoid: bulky" in prompt


def test_presets_expose_three_distinct_customer_roles():
    assert set(PRESET_ROLES) == {"commuter_practical", "gift_buyer", "price_sensitive"}
    assert get_preset_role("gift_buyer") is GIFT_BUYER


def test_policy_updates_seen_items_from_display_response():
    state = RoleState()
    action = RolePolicy().next_action(COMMUTER_PRACTICAL, state, _display(items=[_item("speaker_1", "Bluetooth commute speaker", "Audio")]))

    assert "speaker_1" in state.seen_item_ids
    assert state.turns_observed == 1
    assert action.type in {RoleActionType.WHY, RoleActionType.ACCEPT}


def test_policy_asks_for_concrete_items_when_display_has_no_items():
    state = RoleState()
    action = RolePolicy().next_action(COMMUTER_PRACTICAL, state, _display(items=[]))

    assert action.type == RoleActionType.CHAT
    assert "concrete items" in action.message
    assert state.current_question == "Need more concrete options."


def test_matching_item_can_make_role_ready_to_accept():
    state = RoleState()
    action = RolePolicy().next_action(
        COMMUTER_PRACTICAL,
        state,
        _display(items=[_item("earbuds_1", "Wireless bluetooth commute earbuds", "Audio")]),
    )

    assert action.type == RoleActionType.ACCEPT
    assert action.item_id == "earbuds_1"
    assert state.ready_to_accept is True
    assert state.satisfaction >= 2.0


def test_cautious_role_asks_why_for_partial_match():
    state = RoleState()
    action = RolePolicy().next_action(COMMUTER_PRACTICAL, state, _display(items=[_item("audio_1", "Simple travel pouch", "Audio")]))

    assert action.type == RoleActionType.WHY
    assert action.action_type == "why"
    assert action.item_id == "audio_1"


def test_feedback_style_changes_action_for_weak_match():
    weak_display = _display(items=[_item("unknown_1", "Generic desktop stand", "Office")])

    exploratory = RolePolicy().next_action(GIFT_BUYER, RoleState(), weak_display)
    critical = RolePolicy().next_action(PRICE_SENSITIVE, RoleState(), weak_display)

    assert exploratory.type == RoleActionType.SHOW_DIFFERENT
    assert exploratory.action_type == "show_different"
    assert critical.type == RoleActionType.FEEDBACK
    assert critical.action_type == "dislike"


def _display(items):
    return {
        "schema_version": "rs_agent_display_v1",
        "session_id": "session-1",
        "user_id": "u1",
        "turn_index": 1,
        "assistant_message": "Here are options.",
        "items": items,
        "feedback_actions": [],
        "ui_state": {},
    }


def _item(parent_asin: str, title: str, category: str, price=49.99):
    return {
        "parent_asin": parent_asin,
        "title": title,
        "category": category,
        "price": price,
        "rating": None,
        "store": None,
        "features": [title],
        "description": title,
        "image_url": None,
        "badges": [],
        "summary": title,
    }
