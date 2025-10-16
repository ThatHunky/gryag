import pytest

from app.services.user_profile import UserProfileStore
from app.services.user_profile_adapter import UserProfileStoreAdapter


@pytest.mark.asyncio
async def test_list_chat_users_prioritizes_active_members(test_db):
    store = UserProfileStore(test_db)
    await store.init()

    chat_id = -123

    await store.get_or_create_profile(1, chat_id, display_name="Active", username="active")
    await store.update_profile(1, chat_id, membership_status="member", last_seen=200)

    await store.get_or_create_profile(2, chat_id, display_name="Lefty", username="lefty")
    await store.update_profile(2, chat_id, membership_status="left", last_seen=300)

    all_users = await store.list_chat_users(chat_id, include_inactive=True)
    assert [u["user_id"] for u in all_users] == [1, 2]
    assert all_users[0]["membership_status"] == "member"
    assert all_users[0]["last_interaction_at"] == all_users[0]["last_seen"]

    active_only = await store.list_chat_users(chat_id, include_inactive=False)
    assert len(active_only) == 1
    assert active_only[0]["user_id"] == 1


@pytest.mark.asyncio
async def test_adapter_list_chat_users_matches_store(test_db):
    adapter = UserProfileStoreAdapter(test_db)
    await adapter.init()

    chat_id = -456

    await adapter.get_or_create_profile(10, chat_id, display_name="AdapterUser", username="adapter")
    await adapter.update_profile(10, chat_id, membership_status="member", last_seen=500)

    users = await adapter.list_chat_users(chat_id)
    assert len(users) == 1
    user = users[0]
    assert user["user_id"] == 10
    assert user["membership_status"] == "member"
    assert user["last_interaction_at"] == user["last_seen"]
