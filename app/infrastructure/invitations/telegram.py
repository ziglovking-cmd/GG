"""Telethon boundary: entities, requests, and remote failure translation."""
from __future__ import annotations

import asyncio
from functools import wraps
import time
from typing import Any, Optional

from telethon.errors import PeerIdInvalidError, RPCError, UserNotParticipantError
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl.functions.messages import AddChatUserRequest
from telethon.tl.types import (
    ChannelParticipant,
    ChannelParticipantAdmin,
    ChannelParticipantBanned,
    ChannelParticipantCreator,
    ChannelParticipantLeft,
    ChannelParticipantSelf,
    Chat,
    ChatParticipant,
    ChatParticipantAdmin,
    ChatParticipantCreator,
    InputPeerUser,
    PeerChannel,
    PeerChat,
)

from app.application.invitations.ports import InvitationRepository
from app.domain import invitations as errors, invitations as policy
from app.domain.invitations import InviteNotAcceptedError, MembershipUnknownError, friendly_error


def translate_rpc_errors(operation):
    @wraps(operation)
    async def translated(*args, **kwargs):
        try:
            return await operation(*args, **kwargs)
        except RPCError as error:
            kind = getattr(errors, type(error).__name__, errors.RPCError)
            raise kind(str(error), seconds=int(getattr(error, "seconds", 0))) from error
    return translated


class TelethonInvitationGateway:
    def __init__(self, repo: InvitationRepository) -> None:
        self.repo = repo

    @translate_rpc_errors
    async def is_authorized(self, client) -> bool:
        return await client.is_user_authorized()

    @translate_rpc_errors
    async def resolve_target_chat(self, client, target_chat_id: int):
        """Открывает целевой чат по сохранённому id.

        Голое положительное число Telethon считает id пользователя (PeerUser),
        поэтому id канала/супергруппы оборачиваем в PeerChannel, а обычной
        группы — в PeerChat. Если в кэше сессии аккаунта чата ещё нет, берём его
        по @username, а без username — подтягиваем список диалогов.
        """
        chat_id = int(target_chat_id)
        chat = self.repo.get_chat(chat_id)
        kind = (chat or {}).get("kind")
        username = str((chat or {}).get("username") or "").strip().lstrip("@")
        if kind == "group":
            peers = [PeerChat(chat_id)]
        elif kind in ("supergroup", "channel"):
            peers = [PeerChannel(chat_id)]
        else:
            peers = [PeerChannel(chat_id), PeerChat(chat_id)]

        async def from_cache():
            for peer in peers:
                try:
                    return await client.get_entity(peer)
                except ValueError:
                    continue
            return None

        entity = await from_cache()
        if entity is None and username:
            entity = await client.get_entity(username)
        if entity is None:
            async for _ in client.iter_dialogs():
                pass
            entity = await from_cache()
        if entity is None:
            # Не ValueError: воркер трактует его как ошибку конкретной цели.
            raise RuntimeError(
                "Целевой чат %d не найден: аккаунт не состоит в нём или чат без @username"
                % chat_id
            )
        return entity

    def can_invite(self, entity) -> bool:
        """Аккаунт может добавлять участников: он админ с правом invite_users
        либо чат не запрещает это рядовым участникам."""
        if getattr(entity, "creator", False):
            return True
        rights = getattr(entity, "admin_rights", None)
        if rights is not None and getattr(rights, "invite_users", False):
            return True
        banned = getattr(entity, "default_banned_rights", None)
        if banned is not None and getattr(banned, "invite_users", False):
            return False  # рядовым участникам приглашать запрещено
        return True


    @translate_rpc_errors
    async def resolve_peer(self, client, account_id: int, user_id: int, username: Optional[str]):
        """Сначала свой access_hash, потом @username. Чужой хэш не подойдёт — PEER_ID_INVALID."""
        row = self.repo.get_hash(account_id, user_id)
        if row:
            return InputPeerUser(user_id, int(row["access_hash"]))
        if username:
            entity = await client.get_input_entity(username)
            # запоминаем добытый хэш для этого аккаунта
            if isinstance(entity, InputPeerUser):
                self.repo.save_hash(account_id, entity.user_id, entity.access_hash, int(time.time()))
            return entity
        raise PeerIdInvalidError(request=None)


    @translate_rpc_errors
    async def invite_one(self, client, target_entity, peer) -> None:
        """Отправляет запрос, не принимая ``missing_invitees`` за успех."""
        if isinstance(target_entity, Chat):
            result = await client(
                AddChatUserRequest(chat_id=target_entity.id, user_id=peer, fwd_limit=0)
            )
        else:
            result = await client(
                InviteToChannelRequest(channel=target_entity, users=[peer])
            )
        # С layer 177 Telegram может не бросить RPCError, а вернуть пользователей,
        # для которых приглашение не было выполнено.
        missing = getattr(result, "missing_invitees", None)
        if missing:
            raise InviteNotAcceptedError(
                "Telegram отклонил приглашение и вернул пользователя в missing_invitees"
            )

    async def membership_state_once(
        self,
        client: Any,
        target_entity: Any,
        peer: Any,
    ) -> tuple[str, str]:
        """Возвращает ``present``, ``not_member`` или ``unknown``.

        Telethon ``get_permissions(chat, user)`` использует getParticipant для
        channel/megagroup и точное сравнение user_id в GetFullChat для обычного
        Chat. Ошибка доступа, таймаут или неожиданный тип никогда не становятся
        положительным подтверждением.
        """
        try:
            permissions = await asyncio.wait_for(
                client.get_permissions(target_entity, peer),
                timeout=policy.CAMPAIGN_ACCOUNT_REQUEST_TIMEOUT,
            )
        except UserNotParticipantError:
            return "not_member", ""
        except Exception as error:
            return "unknown", friendly_error(error)

        participant = getattr(permissions, "participant", None)
        if isinstance(
            participant,
            (
                ChannelParticipant,
                ChannelParticipantSelf,
                ChannelParticipantCreator,
                ChannelParticipantAdmin,
                ChatParticipant,
                ChatParticipantAdmin,
                ChatParticipantCreator,
            ),
        ):
            return "present", ""
        if isinstance(participant, ChannelParticipantBanned):
            # ChannelParticipantBanned также представляет ограниченного участника,
            # который всё ещё состоит в megagroup. Он отсутствует только если ушёл
            # или ему запрещён сам просмотр сообщений.
            banned_rights = getattr(participant, "banned_rights", None)
            if (
                not bool(getattr(participant, "left", False))
                and not bool(getattr(banned_rights, "view_messages", False))
            ):
                return "present", ""
            return "not_member", ""
        if isinstance(participant, ChannelParticipantLeft):
            return "not_member", ""
        return "unknown", "Telegram вернул неизвестный тип участника"

    def is_transient_connection_error(self, error: BaseException) -> bool:
        """Отделяет транспортный сбой от подтверждённого ограничения Telegram."""
        if isinstance(error, (RPCError, errors.RPCError, InviteNotAcceptedError, MembershipUnknownError)):
            return False
        if isinstance(error, (asyncio.TimeoutError, TimeoutError, ConnectionError, OSError)):
            return True
        # SQLite writer contention is local infrastructure, not a Telegram limit.
        # Treating it as transient avoids unjustified cooldowns / daily pauses.
        text = (str(error).strip() or error.__class__.__name__).lower()
        if "database is locked" in text or "database table is locked" in text:
            return True
        markers = (
            "connectionerror() takes no keyword arguments",
            "timed out",
            "timeout",
            "proxy",
            "connection reset",
            "connection closed",
            "connection lost",
            "server closed",
            "not connected",
            "disconnected",
            "network is unreachable",
            "socket",
            "eof",
        )
        return any(marker in text for marker in markers)

    def user_id(self, peer: Any) -> Optional[int]:
        return int(peer.user_id) if isinstance(peer, InputPeerUser) else None

    def is_rpc_error(self, error: BaseException) -> bool:
        return isinstance(error, (RPCError, errors.RPCError))
