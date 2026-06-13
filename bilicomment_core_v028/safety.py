from __future__ import annotations

import difflib
import re
import time
from typing import List

from .models import Comment, SafetyResult
from .storage import Storage


DEFAULT_BLOCKED_KEYWORDS = [
    "辱骂",
    "广告",
    "诈骗",
    "政治",
    "色情",
    "违法",
    "引战",
]

AD_PATTERNS = [
    r"https?://",
    r"www\.",
    r"微信",
    r"VX",
    r"QQ ?群",
    r"返钱",
    r"私聊",
    r"加群",
]

ATTACK_WORDS = ["傻", "滚", "废物", "垃圾", "脑残"]


class SafetyChecker:
    def __init__(
        self,
        storage: Storage,
        blocked_keywords: List[str],
        max_replies_per_hour: int,
        max_replies_per_day: int,
    ):
        self.storage = storage
        self.blocked_keywords = [x for x in (blocked_keywords or DEFAULT_BLOCKED_KEYWORDS) if x]
        self.max_replies_per_hour = max_replies_per_hour
        self.max_replies_per_day = max_replies_per_day

    async def check_source_comment(self, comment: Comment) -> SafetyResult:
        flags: List[str] = []
        text = comment.message or ""
        if comment.mid and await self.storage.is_user_blacklisted(comment.mid):
            flags.append("blacklisted_user")
        for keyword in self.blocked_keywords:
            if keyword and keyword in text:
                flags.append(f"source_blocked_keyword:{keyword}")
        if self._has_ad(text):
            flags.append("source_ad")
        if any(word in text for word in ATTACK_WORDS):
            flags.append("source_attack")
        return SafetyResult(allowed=True, flags=flags, reason="需要人工审核" if flags else "")

    async def check_reply_text(self, reply_text: str, oid: int, target_rpid: int, mid: int) -> SafetyResult:
        text = (reply_text or "").strip()
        if not text:
            return SafetyResult.blocked("回复内容不能为空。", ["empty"])
        if len(text) > 200:
            return SafetyResult.blocked("回复超过 200 字，不能直接发送。", ["too_long"])
        flags: List[str] = []
        for keyword in self.blocked_keywords:
            if keyword and keyword in text:
                flags.append(f"blocked_keyword:{keyword}")
        if self._has_ad(text):
            flags.append("ad")
        if any(word in text for word in ATTACK_WORDS):
            flags.append("attack")
        if target_rpid and await self.storage.has_replied_to_comment(target_rpid):
            flags.append("duplicate_target")
        if mid and await self.storage.has_recent_reply_to_user(mid, cooldown_seconds=600):
            flags.append("user_cooldown")
        if await self._is_similar_to_recent(text):
            flags.append("similar_recent")
        now = int(time.time())
        hour_count = await self.storage.count_logs_since(now - 3600)
        day_count = await self.storage.count_logs_since(now - 86400)
        if hour_count >= self.max_replies_per_hour:
            flags.append("hour_rate_limit")
        if day_count >= self.max_replies_per_day:
            flags.append("day_rate_limit")
        if flags:
            return SafetyResult.blocked("安全检查未通过：" + ", ".join(flags), flags)
        return SafetyResult.ok()

    def _has_ad(self, text: str) -> bool:
        return any(re.search(pattern, text, re.IGNORECASE) for pattern in AD_PATTERNS)

    async def _is_similar_to_recent(self, text: str) -> bool:
        for old in await self.storage.recent_reply_texts(limit=20):
            ratio = difflib.SequenceMatcher(a=text, b=old).ratio()
            if ratio >= 0.92:
                return True
        return False
