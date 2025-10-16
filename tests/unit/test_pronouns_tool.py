import json

import pytest

from app.services.user_profile import UserProfileStore
from app.services.tools.memory_tools import set_pronouns_tool


@pytest.mark.asyncio
async def test_set_pronouns_tool_updates_and_clears(test_db):
    store = UserProfileStore(test_db)
    await store.init()

    user_id = 101
    chat_id = 202

    await store.get_or_create_profile(user_id, chat_id)

    result_json = await set_pronouns_tool(
        user_id=user_id,
        pronouns="she/her",
        chat_id=chat_id,
        profile_store=store,
    )
    result = json.loads(result_json)
    assert result["status"] == "success"
    assert result["pronouns"] == "she/her"

    profile = await store.get_profile(user_id, chat_id)
    assert profile is not None
    assert profile.get("pronouns") == "she/her"

    summary = await store.get_user_summary(user_id, chat_id)
    assert "she/her" in summary

    cleared_json = await set_pronouns_tool(
        user_id=user_id,
        pronouns="",
        chat_id=chat_id,
        profile_store=store,
    )
    cleared = json.loads(cleared_json)
    assert cleared["status"] == "success"
    assert cleared["pronouns"] == ""

    profile = await store.get_profile(user_id, chat_id)
    assert profile is not None
    assert profile.get("pronouns") in ("", None)
