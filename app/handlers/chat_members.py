from __future__ import annotations

import time

from aiogram import Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.types import ChatMemberUpdated

from app.services.user_profile import UserProfileStore

router = Router()


_ACTIVE_STATUSES = {
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.CREATOR,
}

_INACTIVE_STATUSES = {
    ChatMemberStatus.LEFT,
    ChatMemberStatus.KICKED,  # KICKED includes banned users in aiogram v3
    ChatMemberStatus.RESTRICTED,
}


@router.chat_member()
async def handle_chat_member_update(
    event: ChatMemberUpdated,
    profile_store: UserProfileStore,
) -> None:
    """Track chat member join/leave events to keep profile roster fresh."""
    chat = event.chat
    if chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return

    member = event.new_chat_member
    user = member.user
    if user is None or user.is_bot:
        return

    chat_id = chat.id
    user_id = user.id
    new_status = member.status
    now = int(time.time())

    if new_status in _ACTIVE_STATUSES:
        await profile_store.get_or_create_profile(
            user_id=user_id,
            chat_id=chat_id,
            display_name=user.full_name,
            username=user.username,
        )
        await profile_store.update_profile(
            user_id=user_id,
            chat_id=chat_id,
            membership_status=new_status.value,
            display_name=user.full_name,
            username=user.username,
            last_seen=now,
        )
    elif new_status in _INACTIVE_STATUSES:
        await profile_store.update_profile(
            user_id=user_id,
            chat_id=chat_id,
            membership_status=new_status.value,
            last_seen=now,
        )
