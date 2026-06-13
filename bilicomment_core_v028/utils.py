from __future__ import annotations

import hashlib
import re
import time
from http.cookies import SimpleCookie
from typing import Any, Dict


def now_ts() -> int:
    return int(time.time())


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_cookie_string(cookie: str) -> Dict[str, str]:
    parsed = SimpleCookie()
    parsed.load(cookie or "")
    return {key: morsel.value for key, morsel in parsed.items()}


def mask_secret(value: str, keep: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}...{value[-keep:]}"


def stable_hash(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()[:12]


def sanitize_plain_text(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"\[CQ:image,[^\]]+\]", "[图片]", text, flags=re.IGNORECASE)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "[图片]", text)
    text = re.sub(r"<img\b[^>]*>", "[图片]", text, flags=re.IGNORECASE)
    text = re.sub(
        r"https?://\S+\.(?:jpg|jpeg|png|gif|webp|bmp|svg)(?:\?\S*)?",
        "[图片链接]",
        text,
        flags=re.IGNORECASE,
    )
    return text.replace("\x00", "").strip()


def summarize_text(value: str, limit: int = 80) -> str:
    text = " ".join(sanitize_plain_text(value).split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "..."
