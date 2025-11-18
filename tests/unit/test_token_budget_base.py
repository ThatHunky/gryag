from app.services.context.token_optimizer import calculate_dynamic_budget


def test_calculate_dynamic_budget_respects_base_allocations():
    base = {
        "immediate": 0.10,
        "recent": 0.50,
        "relevant": 0.20,
        "background": 0.10,
        "episodic": 0.10,
    }
    budgets = calculate_dynamic_budget(
        query_text="звичайне повідомлення",
        recent_message_count=0,
        has_profile_facts=True,
        has_episodes=True,
        base_budgets=base,
    )
    # Sums to ~1.0
    assert 0.999 <= sum(budgets.values()) <= 1.001
    # Recent should remain dominant in base case (no strong adjustments)
    assert budgets["recent"] >= max(
        budgets["immediate"], budgets["relevant"], budgets["background"]
    )


def test_calculate_dynamic_budget_adjusts_for_lookup_queries():
    base = {
        "immediate": 0.20,
        "recent": 0.30,
        "relevant": 0.25,
        "background": 0.15,
        "episodic": 0.10,
    }
    budgets = calculate_dynamic_budget(
        query_text="що таке Python?",
        recent_message_count=0,
        has_profile_facts=True,
        has_episodes=True,
        base_budgets=base,
    )
    # Relevant allocation should increase vs base for lookup queries
    assert budgets["relevant"] > base["relevant"] * 0.9
