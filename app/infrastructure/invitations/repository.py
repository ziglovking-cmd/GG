"""SQLite implementation of the invitation persistence port."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from app import db
from app.domain.invitations import TargetSelection

from .selection import select_candidates


class SqliteInvitationRepository:
    def campaign_stats(self, campaign_id: int) -> Dict[str, int]:
        rows = db.q(
            "SELECT status, COUNT(*) c FROM targets WHERE campaign_id=? GROUP BY status",
            (campaign_id,),
        )
        stats = {r["status"]: r["c"] for r in rows}
        stats["total"] = sum(stats.values())
        return stats

    def has_unresolved_targets(self, campaign_id: int) -> bool:
        row = db.q1(
            "SELECT COUNT(*) c FROM targets WHERE campaign_id=? "
            "AND status IN ('pending','in_progress','verifying')",
            (campaign_id,),
        )
        return bool(row and int(row["c"] or 0))

    def populate_targets(
        self,
        campaign_id: int,
        source_chat_ids: List[int],
        selection: TargetSelection,
    ) -> int:
        """Формирует список целей из спарсенной базы с учётом фильтров и исключений."""
        if not source_chat_ids:
            return 0
        campaign = db.row_to_dict(db.q1("SELECT * FROM campaigns WHERE id=?", (campaign_id,)))
        target_chat_id = campaign["target_chat_id"]

        rows = select_candidates(target_chat_id, source_chat_ids, selection)
        db.exmany(
            "INSERT OR IGNORE INTO targets (campaign_id,user_id,username,display,status) "
            "VALUES (?,?,?,?, 'pending')",
            [(campaign_id, r["user_id"], r["username"], (r["display"] or "").strip()) for r in rows],
        )
        return len(rows)

    def mark(self, target_id: int, status: str, account_id: Optional[int], error: str = '') -> None:
        db.ex(
            "UPDATE targets SET status=?, account_id=?, error=?, attempted_at=? WHERE id=?",
            (status, account_id, error or None, int(time.time()), target_id),
        )

    def requeue_after_technical_failure(self, target_id: int) -> None:
        """Возвращает цель без фиктивной попытки и без изменения attempted_at."""
        db.ex(
            "UPDATE targets SET status='pending', account_id=NULL, error=NULL "
            "WHERE id=? AND status='in_progress'",
            (target_id,),
        )

    def requeue_safe_pre_rpc_claims(self, campaign_id: int) -> None:
        """Requeues only v1 claims proven to be before the Invite RPC."""
        db.ex(
            "UPDATE targets SET status='pending',account_id=NULL,error=NULL "
            "WHERE campaign_id=? AND status='in_progress' AND error=?",
            (int(campaign_id), db.INVITE_CLAIM_MARKER),
        )

    def claim_target(self, campaign_id: int, account_id: int) -> Optional[Dict[str, Any]]:
        """Берёт следующую цель, которую именно этот аккаунт способен пригласить."""
        return db.claim_invite_target(campaign_id, account_id)

    def mark_unreachable(self, campaign_id: int, account_ids: List[int]) -> int:
        """Цели без @username, для которых ни у одного аккаунта в ротации нет access_hash,
        пригласить невозможно — снимаем их с очереди, иначе воркеры будут ждать вечно."""
        if not account_ids:
            return 0
        campaign = self.get_campaign(campaign_id)
        settings = db.settings_of(campaign) if campaign else {}
        mode = str(settings.get("invite_mode") or "hybrid")
        # hybrid: без hash/username → need_link (ручная ссылка), не бесконечный force.
        status = "need_link" if mode == "hybrid" else "no_hash"
        error = (
            "нужна ссылка-приглашение: нет @username и access_hash"
            if status == "need_link"
            else "ни один аккаунт не видел этого пользователя"
        )
        placeholders = ",".join("?" for _ in account_ids)
        db.ex(
            """
            UPDATE targets SET status=?, error=?
            WHERE campaign_id = ? AND status = 'pending'
              AND (username IS NULL OR username = '')
              AND user_id NOT IN (SELECT user_id FROM hashes WHERE account_id IN (%s))
            """ % placeholders,
            [status, error, campaign_id] + list(account_ids),
        )
        left = db.q1(
            "SELECT COUNT(*) c FROM targets WHERE campaign_id=? AND status=?",
            (campaign_id, status),
        )["c"]
        return left

    def get_campaign(self, campaign_id):
        return db.row_to_dict(db.q1('SELECT * FROM campaigns WHERE id=?', (campaign_id,)))

    def get_account(self, account_id):
        return db.row_to_dict(db.q1('SELECT * FROM accounts WHERE id=?', (account_id,)))

    def get_chat(self, chat_id):
        return db.row_to_dict(db.q1('SELECT kind, username FROM chats WHERE id=?', (chat_id,)))

    def get_hash(self, account_id, user_id):
        return db.row_to_dict(
            db.q1(
                'SELECT access_hash FROM hashes WHERE account_id=? AND user_id=?',
                (account_id, user_id),
            ),
        )

    def save_hash(self, account_id, user_id, access_hash, updated_at):
        return db.ex(
            (
                'INSERT INTO hashes (account_id,user_id,access_hash,updated_at) VALUES (?,?,?,?) ON'
                ' CONFLICT(account_id,user_id) DO UPDATE SET access_hash=excluded.access_hash'
            ),
            (account_id, user_id, access_hash, updated_at),
        )

    def running_for_chat(self, chat_id):
        return db.q(
            "SELECT id FROM campaigns WHERE target_chat_id=? AND status='running' ORDER BY id",
            (chat_id,),
        )

    def save_resolved_id(self, user_id, target_id):
        return db.ex('UPDATE targets SET resolved_user_id=? WHERE id=?', (user_id, target_id,))

    def save_verification_error(self, error, target_id):
        return db.ex("UPDATE targets SET error=? WHERE id=? AND status='verifying'", (error, target_id,))

    def campaign_next_invite(self, campaign_id):
        return db.row_to_dict(
            db.q1(
                "SELECT next_invite_at, wave_pause_until, wave_progress, settings, "
                "target_chat_id FROM campaigns WHERE id=?",
                (campaign_id,),
            )
        )

    def chat_confirmed_today(self, target_chat_id: int) -> int:
        return db.chat_confirmed_today(int(target_chat_id))

    def reserve_campaign(self, next_at, campaign_id):
        return db.ex('UPDATE campaigns SET next_invite_at=? WHERE id=?', (next_at, campaign_id,))

    def release_campaign(self, campaign_id, reserved_at):
        return db.ex(
            'UPDATE campaigns SET next_invite_at=0 WHERE id=? AND next_invite_at=?',
            (campaign_id, reserved_at),
        )

    def restore_technical_account(self, account_id):
        return db.ex(
            (
                "UPDATE accounts SET can_invite=1, status='authorized', last_error=NULL, "
                'cooldown_until=0 WHERE id=?'
            ),
            (account_id,),
        )

    def restore_account(self, account_id):
        return db.ex(
            "UPDATE accounts SET can_invite=1, status='authorized', last_error=NULL WHERE id=?",
            (account_id,),
        )

    def set_campaign_status(self, status, campaign_id):
        return db.ex('UPDATE campaigns SET status=? WHERE id=?', (status, campaign_id,))

    def pending_verification(self, campaign_id, account_id, marker):
        return db.row_to_dict(
            db.q1(
                "\n        SELECT * FROM targets\n        WHERE campaign_id=? AND account_id=? AND status='verifying'\n          AND (\n              error LIKE ?\n              OR error LIKE 'запрос отправлен, проверяю фактическое присутствие%'\n              OR error LIKE 'Не удалось достоверно подтвердить присутствие%'\n          )\n        ORDER BY attempted_at,id LIMIT 1\n        ",
                (campaign_id, account_id, marker),
            ),
        )

    def log(self, message: str, **context) -> None:
        db.log(message, **context)

    def mark_invite_rpc_started(self, target_id, account_id, note):
        return db.mark_invite_rpc_started(target_id, account_id, note)

    def finalize_invite_confirmation(self, target_id, present, **kwargs):
        return db.finalize_invite_confirmation(target_id, present, **kwargs)
