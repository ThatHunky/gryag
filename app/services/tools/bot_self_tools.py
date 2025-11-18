"""Gemini tools for bot self-awareness - bot can query its own learned patterns."""

from __future__ import annotations

import json
import logging

from app.services.bot_profile import BotProfileStore

LOGGER = logging.getLogger(__name__)


# Tool definition for Gemini
QUERY_BOT_SELF_TOOL_DEFINITION = {
    "name": "query_bot_self",
    "description": (
        "Query your own learned patterns and facts. Use this to understand what you've "
        "learned about yourself - communication patterns that work well, knowledge gaps, "
        "temporal patterns, tool effectiveness, etc. Helps you adapt your responses based "
        "on past experience."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "fact_category": {
                "type": "string",
                "description": (
                    "Category of facts to query. Options: communication_style, "
                    "knowledge_domain, tool_effectiveness, user_interaction, "
                    "persona_adjustment, mistake_pattern, temporal_pattern, performance_metric"
                ),
                "enum": [
                    "communication_style",
                    "knowledge_domain",
                    "tool_effectiveness",
                    "user_interaction",
                    "persona_adjustment",
                    "mistake_pattern",
                    "temporal_pattern",
                    "performance_metric",
                ],
            },
            "context_tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional context tags to filter facts (e.g., 'evening', 'weekend', "
                    "'technical', 'formal')"
                ),
            },
            "min_confidence": {
                "type": "number",
                "description": "Minimum confidence threshold (0.0-1.0), default 0.5",
                "default": 0.5,
            },
        },
        "required": [],
    },
}


async def query_bot_self_tool(
    bot_profile: BotProfileStore,
    chat_id: int,
    fact_category: str | None = None,
    context_tags: list[str] | None = None,
    min_confidence: float = 0.5,
) -> str:
    """
    Tool implementation: Query bot's own learned facts.

    Returns JSON string with learned facts.
    """
    try:
        # Get facts
        facts = await bot_profile.get_facts(
            category=fact_category,
            min_confidence=min_confidence,
            chat_id=chat_id,
            context_tags=context_tags,
            apply_temporal_decay=True,
            limit=20,
        )

        # Get effectiveness summary
        summary = await bot_profile.get_effectiveness_summary(chat_id=chat_id, days=7)

        # Get recent insights
        insights = await bot_profile.get_recent_insights(
            chat_id=chat_id,
            insight_type=None,
            actionable_only=False,
            limit=5,
        )

        # Format response
        result = {
            "effectiveness": {
                "score": summary["effectiveness_score"],
                "recent_score": summary["recent_effectiveness"],
                "total_interactions": summary["total_interactions"],
                "positive_rate": (
                    summary["positive_interactions"] / summary["total_interactions"]
                    if summary["total_interactions"] > 0
                    else 0
                ),
            },
            "learned_facts": [
                {
                    "category": f["fact_category"],
                    "key": f["fact_key"],
                    "value": f["fact_value"],
                    "confidence": f.get("effective_confidence", f["confidence"]),
                    "evidence_count": f["evidence_count"],
                    "source": f["source_type"],
                }
                for f in facts[:10]  # Top 10 most relevant
            ],
            "recent_insights": [
                {
                    "type": i["insight_type"],
                    "text": i["insight_text"],
                    "confidence": i["confidence"],
                    "actionable": bool(i["actionable"]),
                }
                for i in insights
            ],
        }

        LOGGER.info(
            f"Bot queried self: category={fact_category}, found {len(facts)} facts"
        )
        return json.dumps(result, ensure_ascii=False)

    except Exception as e:
        LOGGER.error(f"Failed to query bot self: {e}", exc_info=True)
        return json.dumps(
            {"error": f"Failed to query self-knowledge: {str(e)}"},
            ensure_ascii=False,
        )


# Get effectiveness summary tool
GET_BOT_EFFECTIVENESS_TOOL_DEFINITION = {
    "name": "get_bot_effectiveness",
    "description": (
        "Get a summary of your own effectiveness metrics - response times, "
        "user satisfaction, outcome distribution. Use this to understand how well "
        "you're performing."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "Number of days to look back (default 7)",
                "default": 7,
            }
        },
        "required": [],
    },
}


async def get_bot_effectiveness_tool(
    bot_profile: BotProfileStore,
    chat_id: int,
    days: int = 7,
) -> str:
    """
    Tool implementation: Get bot effectiveness summary.

    Returns JSON string with metrics.
    """
    try:
        summary = await bot_profile.get_effectiveness_summary(
            chat_id=chat_id, days=days
        )

        result = {
            "period_days": days,
            "effectiveness_score": summary["effectiveness_score"],
            "recent_effectiveness": summary["recent_effectiveness"],
            "total_interactions": summary["total_interactions"],
            "positive_interactions": summary["positive_interactions"],
            "negative_interactions": summary["negative_interactions"],
            "outcome_distribution": summary["recent_outcomes"],
            "performance": {
                "avg_response_time_ms": summary["avg_response_time_ms"],
                "avg_token_count": summary["avg_token_count"],
                "avg_sentiment": summary["avg_sentiment"],
            },
        }

        LOGGER.info(
            f"Bot queried effectiveness: {summary['recent_effectiveness']:.2%} over {days} days"
        )
        return json.dumps(result, ensure_ascii=False)

    except Exception as e:
        LOGGER.error(f"Failed to get bot effectiveness: {e}", exc_info=True)
        return json.dumps(
            {"error": f"Failed to get effectiveness metrics: {str(e)}"},
            ensure_ascii=False,
        )
