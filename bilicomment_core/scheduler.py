from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional

from .bilibili_client import BilibiliClient
from .models import ReplyDraft
from .reply_generator import ReplyGenerator
from .safety import SafetyChecker
from .storage import Storage
from .utils import now_ts, summarize_text


NotifyFunc = Callable[[str, str], Awaitable[None]]
FlagFunc = Callable[[], bool]


class MonitorScheduler:
    def __init__(
        self,
        *,
        storage: Storage,
        client: BilibiliClient,
        generator: ReplyGenerator,
        safety: SafetyChecker,
        notify: NotifyFunc,
        auto_reply_enabled: FlagFunc,
        dry_run: FlagFunc,
        require_confirmation: FlagFunc,
        tick_seconds: int = 10,
    ):
        self.storage = storage
        self.client = client
        self.generator = generator
        self.safety = safety
        self.notify = notify
        self.auto_reply_enabled = auto_reply_enabled
        self.dry_run = dry_run
        self.require_confirmation = require_confirmation
        self.tick_seconds = max(tick_seconds, 5)
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def run_once(self) -> None:
        tasks = await self.storage.list_monitor_tasks(include_disabled=False)
        current = now_ts()
        for task in tasks:
            if task.last_checked_at and current - task.last_checked_at < task.interval_seconds:
                continue
            try:
                await self._run_task(task)
            except Exception as exc:
                await self.notify(
                    f"监听任务 {task.task_id} 执行失败：{exc}",
                    task.notify_origin,
                )

    async def _loop(self) -> None:
        while True:
            await self.run_once()
            await asyncio.sleep(self.tick_seconds)

    async def _run_task(self, task) -> None:
        try:
            comments = await self.client.get_replies(
                oid=task.aid,
                type_=1,
                page=1,
                sort=1,
                bvid=task.bvid,
            )
        except TypeError as exc:
            if "unexpected keyword argument 'bvid'" not in str(exc):
                raise
            comments = await self.client.get_replies(oid=task.aid, type_=1, page=1, sort=1)
        newest_rpid = max((comment.rpid for comment in comments), default=task.last_seen_rpid or 0)
        if task.last_seen_rpid is None:
            for comment in comments:
                await self.storage.save_seen_comment(comment)
            await self.storage.update_monitor_progress(
                task.task_id,
                last_checked_at=now_ts(),
                last_seen_rpid=newest_rpid,
            )
            await self.notify(
                f"监听任务 {task.task_id} 已完成首次扫描，已记录现有评论，后续只处理新评论。",
                task.notify_origin,
            )
            return

        new_comments = [
            comment for comment in comments if comment.rpid > int(task.last_seen_rpid or 0)
        ]
        for comment in reversed(new_comments):
            await self.storage.save_seen_comment(comment)
            await self._handle_comment(task, comment)
        await self.storage.update_monitor_progress(
            task.task_id,
            last_checked_at=now_ts(),
            last_seen_rpid=newest_rpid,
        )

    async def _handle_comment(self, task, comment) -> None:
        if task.mode == "notify_only":
            await self.notify(
                f"视频《{task.title}》有新评论：{comment.uname} | rpid={comment.rpid} | "
                f"{summarize_text(comment.message, 80)}",
                task.notify_origin,
            )
            return

        source_safety = await self.safety.check_source_comment(comment)
        reply_text = await self.generator.generate(
            video_title=task.title,
            comment=comment,
            style="friendly",
        )
        reply_safety = await self.safety.check_reply_text(
            reply_text=reply_text,
            oid=comment.oid,
            target_rpid=comment.rpid,
            mid=comment.mid,
        )
        flags = sorted(set(source_safety.flags + reply_safety.flags))
        draft = ReplyDraft.new(
            oid=comment.oid,
            type=comment.type,
            target_rpid=comment.rpid,
            target_mid=comment.mid,
            root=comment.reply_root,
            parent=comment.reply_parent,
            source_comment=comment.message,
            reply_text=reply_text,
            safety_flags=flags,
        )

        if task.mode != "auto_reply":
            await self.storage.create_reply_draft(draft)
            await self.notify(self._draft_notice(task, draft, flags), task.notify_origin)
            return

        if (
            not self.auto_reply_enabled()
            or self.require_confirmation()
            or not reply_safety.allowed
            or source_safety.flags
        ):
            await self.storage.create_reply_draft(draft)
            await self.notify(self._draft_notice(task, draft, flags), task.notify_origin)
            return

        if self.dry_run():
            await self.storage.create_reply_draft(draft)
            await self.storage.write_reply_log(
                draft_id=draft.draft_id,
                oid=draft.oid,
                target_rpid=draft.target_rpid,
                reply_text=draft.reply_text,
                success=True,
                error_message="dry_run",
                target_mid=draft.target_mid,
            )
            await self.notify(
                f"[dry-run] 自动回复任务 {task.task_id} 将回复：{draft.reply_text}",
                task.notify_origin,
            )
            return

        await self.storage.create_reply_draft(draft)
        await self.client.send_reply(
            oid=draft.oid,
            type_=draft.type,
            message=draft.reply_text,
            root=draft.root,
            parent=draft.parent,
        )
        await self.storage.update_draft_status(draft.draft_id, "sent")
        await self.storage.write_reply_log(
            draft_id=draft.draft_id,
            oid=draft.oid,
            target_rpid=draft.target_rpid,
            reply_text=draft.reply_text,
            success=True,
            error_message=None,
            target_mid=draft.target_mid,
        )
        await self.notify(
            f"自动回复任务 {task.task_id} 已发送评论：{draft.reply_text}",
            task.notify_origin,
        )

    def _draft_notice(self, task, draft: ReplyDraft, flags) -> str:
        return "\n".join(
            [
                f"监听任务 {task.task_id} 生成新草稿：{draft.draft_id}",
                f"视频：{task.title}",
                f"目标 rpid：{draft.target_rpid}（root={draft.root}, parent={draft.parent}）",
                f"安全标记：{', '.join(flags) if flags else '无'}",
                f"草稿：{draft.reply_text}",
                f"发送：/bili_send {draft.draft_id}",
            ]
        )
