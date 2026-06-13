from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import List, Optional

import aiosqlite

from .models import Comment, ReplyDraft, ReplyLog
from .models import MonitorTask
from .utils import now_ts


class Storage:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    async def init(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS monitor_tasks (
                    task_id TEXT PRIMARY KEY,
                    bvid TEXT,
                    aid INTEGER,
                    title TEXT,
                    enabled INTEGER,
                    interval_seconds INTEGER,
                    last_checked_at INTEGER,
                    last_seen_rpid INTEGER,
                    mode TEXT,
                    created_by TEXT,
                    created_at INTEGER,
                    notify_origin TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS seen_comments (
                    rpid INTEGER PRIMARY KEY,
                    oid INTEGER,
                    type INTEGER,
                    root INTEGER DEFAULT 0,
                    parent INTEGER DEFAULT 0,
                    message TEXT,
                    uname TEXT,
                    mid INTEGER,
                    ctime INTEGER,
                    like_count INTEGER DEFAULT 0,
                    replies_count INTEGER DEFAULT 0,
                    first_seen_at INTEGER
                );

                CREATE TABLE IF NOT EXISTS reply_drafts (
                    draft_id TEXT PRIMARY KEY,
                    oid INTEGER,
                    type INTEGER,
                    target_rpid INTEGER,
                    target_mid INTEGER DEFAULT 0,
                    root INTEGER,
                    parent INTEGER,
                    source_comment TEXT,
                    reply_text TEXT,
                    status TEXT,
                    safety_flags TEXT,
                    created_at INTEGER,
                    updated_at INTEGER
                );

                CREATE TABLE IF NOT EXISTS reply_logs (
                    log_id TEXT PRIMARY KEY,
                    draft_id TEXT,
                    oid INTEGER,
                    target_rpid INTEGER,
                    reply_text TEXT,
                    success INTEGER,
                    error_message TEXT,
                    created_at INTEGER
                );

                CREATE TABLE IF NOT EXISTS rate_limits (
                    key TEXT PRIMARY KEY,
                    count INTEGER,
                    window_start INTEGER
                );

                CREATE TABLE IF NOT EXISTS blacklisted_users (
                    mid TEXT PRIMARY KEY,
                    reason TEXT,
                    created_at INTEGER
                );

                CREATE TABLE IF NOT EXISTS user_reply_cooldowns (
                    mid TEXT PRIMARY KEY,
                    last_replied_at INTEGER
                );
                """
            )
            await self._ensure_columns(db)
            await db.commit()

    async def _ensure_columns(self, db: aiosqlite.Connection) -> None:
        async with db.execute("PRAGMA table_info(monitor_tasks)") as cursor:
            columns = {row[1] for row in await cursor.fetchall()}
        if "notify_origin" not in columns:
            await db.execute("ALTER TABLE monitor_tasks ADD COLUMN notify_origin TEXT DEFAULT ''")
        async with db.execute("PRAGMA table_info(seen_comments)") as cursor:
            seen_columns = {row[1] for row in await cursor.fetchall()}
        seen_defaults = {
            "root": "INTEGER DEFAULT 0",
            "parent": "INTEGER DEFAULT 0",
            "like_count": "INTEGER DEFAULT 0",
            "replies_count": "INTEGER DEFAULT 0",
        }
        for column, definition in seen_defaults.items():
            if column not in seen_columns:
                await db.execute(f"ALTER TABLE seen_comments ADD COLUMN {column} {definition}")
        async with db.execute("PRAGMA table_info(reply_drafts)") as cursor:
            draft_columns = {row[1] for row in await cursor.fetchall()}
        if "target_mid" not in draft_columns:
            await db.execute("ALTER TABLE reply_drafts ADD COLUMN target_mid INTEGER DEFAULT 0")

    async def save_seen_comment(self, comment: Comment) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO seen_comments
                (rpid, oid, type, root, parent, message, uname, mid, ctime,
                 like_count, replies_count, first_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(rpid) DO UPDATE SET
                    root = excluded.root,
                    parent = excluded.parent,
                    message = excluded.message,
                    uname = excluded.uname,
                    mid = excluded.mid,
                    ctime = excluded.ctime,
                    like_count = excluded.like_count,
                    replies_count = excluded.replies_count
                """,
                (
                    comment.rpid,
                    comment.oid,
                    comment.type,
                    comment.root,
                    comment.parent,
                    comment.message,
                    comment.uname,
                    comment.mid,
                    comment.ctime,
                    comment.like,
                    comment.replies_count,
                    now_ts(),
                ),
            )
            await db.commit()

    async def get_seen_comment(self, rpid: int) -> Optional[Comment]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """
                SELECT rpid, oid, type, root, parent, message, uname, mid, ctime,
                       like_count, replies_count
                FROM seen_comments WHERE rpid = ?
                """,
                (rpid,),
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return Comment(
            rpid=row[0],
            oid=row[1],
            type=row[2],
            root=row[3],
            parent=row[4],
            mid=row[7],
            uname=row[6],
            message=row[5],
            ctime=row[8],
            like=row[9],
            replies_count=row[10],
        )

    async def create_reply_draft(self, draft: ReplyDraft) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO reply_drafts
                (draft_id, oid, type, target_rpid, target_mid, root, parent, source_comment,
                 reply_text, status, safety_flags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft.draft_id,
                    draft.oid,
                    draft.type,
                    draft.target_rpid,
                    draft.target_mid,
                    draft.root,
                    draft.parent,
                    draft.source_comment,
                    draft.reply_text,
                    draft.status,
                    json.dumps(draft.safety_flags, ensure_ascii=False),
                    draft.created_at,
                    draft.updated_at,
                ),
            )
            await db.commit()

    async def get_reply_draft(self, draft_id: str) -> Optional[ReplyDraft]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """
                SELECT draft_id, oid, type, target_rpid, target_mid, root, parent, source_comment,
                       reply_text, status, safety_flags, created_at, updated_at
                FROM reply_drafts WHERE draft_id = ?
                """,
                (draft_id,),
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_draft(row)

    async def list_pending_drafts(self, limit: int = 10) -> List[ReplyDraft]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """
                SELECT draft_id, oid, type, target_rpid, target_mid, root, parent, source_comment,
                       reply_text, status, safety_flags, created_at, updated_at
                FROM reply_drafts
                WHERE status = 'pending'
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_draft(row) for row in rows]

    async def update_draft_text(self, draft_id: str, reply_text: str, safety_flags: List[str]) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE reply_drafts
                SET reply_text = ?, safety_flags = ?, updated_at = ?
                WHERE draft_id = ?
                """,
                (reply_text, json.dumps(safety_flags, ensure_ascii=False), now_ts(), draft_id),
            )
            await db.commit()

    async def update_draft_status(
        self,
        draft_id: str,
        status: str,
        safety_flags: Optional[List[str]] = None,
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            if safety_flags is None:
                await db.execute(
                    "UPDATE reply_drafts SET status = ?, updated_at = ? WHERE draft_id = ?",
                    (status, now_ts(), draft_id),
                )
            else:
                await db.execute(
                    """
                    UPDATE reply_drafts SET status = ?, safety_flags = ?, updated_at = ?
                    WHERE draft_id = ?
                    """,
                    (status, json.dumps(safety_flags, ensure_ascii=False), now_ts(), draft_id),
                )
            await db.commit()

    async def write_reply_log(
        self,
        *,
        draft_id: Optional[str],
        oid: int,
        target_rpid: int,
        reply_text: str,
        success: bool,
        error_message: Optional[str],
        target_mid: int | str = 0,
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO reply_logs
                (log_id, draft_id, oid, target_rpid, reply_text, success, error_message, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"log_{uuid.uuid4().hex[:12]}",
                    draft_id,
                    oid,
                    target_rpid,
                    reply_text,
                    1 if success else 0,
                    error_message,
                    now_ts(),
                ),
            )
            if success and error_message is None and str(target_mid or ""):
                await db.execute(
                    """
                    INSERT INTO user_reply_cooldowns (mid, last_replied_at)
                    VALUES (?, ?)
                    ON CONFLICT(mid) DO UPDATE SET last_replied_at = excluded.last_replied_at
                    """,
                    (str(target_mid), now_ts()),
                )
            await db.commit()

    async def list_reply_logs(self, limit: int = 10) -> List[ReplyLog]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """
                SELECT log_id, draft_id, oid, target_rpid, reply_text, success, error_message, created_at
                FROM reply_logs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [
            ReplyLog(
                log_id=row[0],
                draft_id=row[1],
                oid=row[2],
                target_rpid=row[3],
                reply_text=row[4],
                success=bool(row[5]),
                error_message=row[6],
                created_at=row[7],
            )
            for row in rows
        ]

    async def count_logs_since(self, since_ts: int, success_only: bool = True) -> int:
        sql = "SELECT COUNT(*) FROM reply_logs WHERE created_at >= ?"
        params = [since_ts]
        if success_only:
            sql += " AND success = 1 AND (error_message IS NULL OR error_message != 'dry_run')"
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(sql, tuple(params)) as cursor:
                row = await cursor.fetchone()
        return int(row[0] if row else 0)

    async def count_logs_today(self) -> int:
        now = int(time.time())
        today_start = now - (now % 86400)
        return await self.count_logs_since(today_start, success_only=False)

    async def has_replied_to_comment(self, target_rpid: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """
                SELECT COUNT(*) FROM reply_logs
                WHERE target_rpid = ? AND success = 1
                  AND (error_message IS NULL OR error_message != 'dry_run')
                """,
                (target_rpid,),
            ) as cursor:
                row = await cursor.fetchone()
        return bool(row and row[0])

    async def recent_reply_texts(self, limit: int = 20) -> List[str]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT reply_text FROM reply_logs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [str(row[0]) for row in rows]

    async def add_blacklisted_user(self, mid: str, reason: str = "") -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO blacklisted_users (mid, reason, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(mid) DO UPDATE SET reason = excluded.reason
                """,
                (str(mid), reason, now_ts()),
            )
            await db.commit()

    async def remove_blacklisted_user(self, mid: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("DELETE FROM blacklisted_users WHERE mid = ?", (str(mid),))
            await db.commit()
            return cursor.rowcount > 0

    async def is_user_blacklisted(self, mid: int | str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT 1 FROM blacklisted_users WHERE mid = ?",
                (str(mid),),
            ) as cursor:
                row = await cursor.fetchone()
        return row is not None

    async def list_blacklisted_users(self, limit: int = 50) -> List[tuple[str, str, int]]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """
                SELECT mid, reason, created_at
                FROM blacklisted_users
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [(str(row[0]), str(row[1] or ""), int(row[2] or 0)) for row in rows]

    async def has_recent_reply_to_user(self, mid: int | str, cooldown_seconds: int = 600) -> bool:
        if not str(mid or ""):
            return False
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT last_replied_at FROM user_reply_cooldowns WHERE mid = ?",
                (str(mid),),
            ) as cursor:
                row = await cursor.fetchone()
        return bool(row and now_ts() - int(row[0] or 0) < cooldown_seconds)

    async def add_monitor_task(self, task: MonitorTask) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO monitor_tasks
                (task_id, bvid, aid, title, enabled, interval_seconds, last_checked_at,
                 last_seen_rpid, mode, created_by, created_at, notify_origin)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    task.bvid,
                    task.aid,
                    task.title,
                    1 if task.enabled else 0,
                    task.interval_seconds,
                    task.last_checked_at,
                    task.last_seen_rpid,
                    task.mode,
                    task.created_by,
                    task.created_at,
                    task.notify_origin,
                ),
            )
            await db.commit()

    async def list_monitor_tasks(self, include_disabled: bool = True) -> List[MonitorTask]:
        where = "" if include_disabled else "WHERE enabled = 1"
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                f"""
                SELECT task_id, bvid, aid, title, enabled, interval_seconds,
                       last_checked_at, last_seen_rpid, mode, created_by, created_at,
                       notify_origin
                FROM monitor_tasks
                {where}
                ORDER BY created_at DESC
                """
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_monitor_task(row) for row in rows]

    async def get_monitor_task(self, task_id: str) -> Optional[MonitorTask]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """
                SELECT task_id, bvid, aid, title, enabled, interval_seconds,
                       last_checked_at, last_seen_rpid, mode, created_by, created_at,
                       notify_origin
                FROM monitor_tasks
                WHERE task_id = ?
                """,
                (task_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return self._row_to_monitor_task(row) if row else None

    async def set_monitor_enabled(self, task_id: str, enabled: bool) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE monitor_tasks SET enabled = ? WHERE task_id = ?",
                (1 if enabled else 0, task_id),
            )
            await db.commit()

    async def remove_monitor_task(self, task_id: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("DELETE FROM monitor_tasks WHERE task_id = ?", (task_id,))
            await db.commit()
            return cursor.rowcount > 0

    async def update_monitor_progress(
        self,
        task_id: str,
        *,
        last_checked_at: int,
        last_seen_rpid: Optional[int],
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE monitor_tasks
                SET last_checked_at = ?, last_seen_rpid = COALESCE(?, last_seen_rpid)
                WHERE task_id = ?
                """,
                (last_checked_at, last_seen_rpid, task_id),
            )
            await db.commit()

    def _row_to_draft(self, row) -> ReplyDraft:
        try:
            flags = json.loads(row[10] or "[]")
        except ValueError:
            flags = []
        return ReplyDraft(
            draft_id=row[0],
            oid=row[1],
            type=row[2],
            target_rpid=row[3],
            target_mid=row[4],
            root=row[5],
            parent=row[6],
            source_comment=row[7],
            reply_text=row[8],
            status=row[9],
            safety_flags=flags,
            created_at=row[11],
            updated_at=row[12],
        )

    def _row_to_monitor_task(self, row) -> MonitorTask:
        return MonitorTask(
            task_id=row[0],
            bvid=row[1],
            aid=row[2],
            title=row[3],
            enabled=bool(row[4]),
            interval_seconds=row[5],
            last_checked_at=row[6],
            last_seen_rpid=row[7],
            mode=row[8],
            created_by=row[9],
            created_at=row[10],
            notify_origin=row[11] or "",
        )
