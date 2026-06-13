from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Comment:
    rpid: int
    oid: int
    type: int
    root: int
    parent: int
    mid: int
    uname: str
    message: str
    ctime: int
    like: int
    replies_count: int
    is_up: bool = False
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_bili(cls, item: Dict[str, Any], oid: int, type_: int) -> "Comment":
        member = item.get("member") or {}
        content = item.get("content") or {}
        return cls(
            rpid=int(item.get("rpid") or 0),
            oid=int(oid),
            type=int(type_),
            root=int(item.get("root") or 0),
            parent=int(item.get("parent") or 0),
            mid=int(member.get("mid") or item.get("mid") or 0),
            uname=str(member.get("uname") or ""),
            message=str(content.get("message") or ""),
            ctime=int(item.get("ctime") or 0),
            like=int(item.get("like") or 0),
            replies_count=int(item.get("rcount") or 0),
            is_up=bool(member.get("is_up") or False),
            raw=item,
        )

    @property
    def is_thread_reply(self) -> bool:
        return self.root > 0

    @property
    def level_label(self) -> str:
        return "评论回复" if self.is_thread_reply else "主评论"

    @property
    def reply_root(self) -> int:
        return self.root or self.rpid

    @property
    def reply_parent(self) -> int:
        return self.rpid


@dataclass
class ReplyDraft:
    draft_id: str
    oid: int
    type: int
    target_rpid: int
    root: int
    parent: int
    source_comment: str
    reply_text: str
    status: str
    created_at: int
    updated_at: int
    target_mid: int = 0
    safety_flags: List[str] = field(default_factory=list)

    @classmethod
    def new(
        cls,
        *,
        oid: int,
        type: int,
        target_rpid: int,
        target_mid: int = 0,
        root: int,
        parent: int,
        source_comment: str,
        reply_text: str,
        safety_flags: Optional[List[str]] = None,
    ) -> "ReplyDraft":
        ts = int(time.time())
        return cls(
            draft_id=f"draft_{uuid.uuid4().hex[:12]}",
            oid=oid,
            type=type,
            target_rpid=target_rpid,
            target_mid=target_mid,
            root=root,
            parent=parent,
            source_comment=source_comment,
            reply_text=reply_text,
            status="pending",
            created_at=ts,
            updated_at=ts,
            safety_flags=safety_flags or [],
        )


@dataclass
class MonitorTask:
    task_id: str
    bvid: str
    aid: int
    title: str
    enabled: bool
    interval_seconds: int
    last_checked_at: int
    last_seen_rpid: Optional[int]
    mode: str
    created_by: str
    created_at: int = 0
    notify_origin: str = ""

    @classmethod
    def new(
        cls,
        *,
        bvid: str,
        aid: int,
        title: str,
        interval_seconds: int,
        mode: str,
        created_by: str,
        notify_origin: str,
    ) -> "MonitorTask":
        return cls(
            task_id=f"mon_{uuid.uuid4().hex[:10]}",
            bvid=bvid,
            aid=aid,
            title=title,
            enabled=True,
            interval_seconds=interval_seconds,
            last_checked_at=0,
            last_seen_rpid=None,
            mode=mode,
            created_by=created_by,
            created_at=int(time.time()),
            notify_origin=notify_origin,
        )


@dataclass
class ReplyLog:
    log_id: str
    draft_id: Optional[str]
    oid: int
    target_rpid: int
    reply_text: str
    success: bool
    error_message: Optional[str]
    created_at: int


@dataclass
class AccountStatus:
    uname: str
    mid: int
    is_login: bool


@dataclass
class SafetyResult:
    allowed: bool
    flags: List[str] = field(default_factory=list)
    reason: str = ""

    @classmethod
    def ok(cls) -> "SafetyResult":
        return cls(True, [], "")

    @classmethod
    def blocked(cls, reason: str, flags: Optional[List[str]] = None) -> "SafetyResult":
        return cls(False, flags or [], reason)
