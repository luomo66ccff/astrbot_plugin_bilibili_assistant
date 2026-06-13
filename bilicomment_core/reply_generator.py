from __future__ import annotations

import re
from typing import Optional

from .models import Comment
from .rules import RuleEngine


class ReplyGenerator:
    def __init__(
        self,
        context,
        rules: RuleEngine,
        default_style: str = "friendly",
        chat_provider_id: Optional[str] = None,
    ):
        self.context = context
        self.rules = rules
        self.default_style = default_style
        self.chat_provider_id = chat_provider_id
        self.last_source = "unknown"
        self.last_error = ""
        self.last_provider_id = ""

    async def generate(
        self,
        video_title: str,
        comment: Comment,
        style: Optional[str] = None,
        chat_provider_id: Optional[str] = None,
    ) -> str:
        style = style or self.default_style
        provider_id = chat_provider_id or self.chat_provider_id
        try:
            self.last_provider_id = provider_id or ""
            self.last_error = ""
            self.last_source = "ai"
            return await self._llm_generate(
                video_title,
                comment,
                style,
                chat_provider_id=provider_id,
            )
        except Exception as exc:
            self.last_source = "template"
            self.last_error = str(exc) or exc.__class__.__name__
            return self.rules.template_reply(comment, style)

    async def generate_from_text(
        self,
        content: str,
        *,
        style: Optional[str] = None,
        video_title: str = "",
        chat_provider_id: Optional[str] = None,
    ) -> str:
        comment = Comment(
            rpid=0,
            oid=0,
            type=1,
            root=0,
            parent=0,
            mid=0,
            uname="用户",
            message=content,
            ctime=0,
            like=0,
            replies_count=0,
        )
        style = style or self.default_style
        provider_id = chat_provider_id or self.chat_provider_id
        try:
            self.last_provider_id = provider_id or ""
            self.last_error = ""
            self.last_source = "ai"
            return await self._llm_generate(video_title, comment, style, chat_provider_id=provider_id)
        except Exception as exc:
            self.last_source = "template"
            self.last_error = str(exc) or exc.__class__.__name__
            return self.rules.template_reply(comment, style)

    async def _llm_generate(
        self,
        video_title: str,
        comment: Comment,
        style: str,
        chat_provider_id: Optional[str] = None,
    ) -> str:
        provider_id = chat_provider_id or self.chat_provider_id
        kind = self.rules.classify(comment)
        style_hint = {
            "friendly": "自然友好，像UP主认真回复粉丝。",
            "official": "正式克制，适合公告或运营号。",
            "cute": "轻松可爱，但不要过度卖萌。",
            "concise": "短句直接，尽量不超过30字。",
            "humorous": "轻微幽默，但不要阴阳怪气。",
        }.get(style, "自然友好，像UP主认真回复粉丝。")
        level = comment.level_label if getattr(comment, "level_label", "") else "主评论"
        title = video_title or "未提供"
        prompt = (
            "你是B站UP主评论区助手。\n"
            "任务：只根据下方评论内容，生成一条可以直接发到B站评论区的回复。\n"
            "判断要求：先判断用户是在夸赞、提问、催更、反馈问题、负面评价还是普通互动，再选择合适回应。\n"
            "安全限制：不要承诺无法保证的事情；不要攻击或嘲讽用户；不要引战；不要诱导刷赞、刷关注；"
            "不知道答案时要礼貌说明会确认或补充，不要编造事实。\n"
            "输出要求：只输出回复文本，不要解释、不要编号、不要加引号；长度控制在15-80字；尽量一行。\n"
            f"视频标题：{title}\n"
            f"评论层级：{level}\n"
            f"评论用户名：{comment.uname}\n"
            f"评论内容：{comment.message}\n"
            f"评论分类：{kind}\n"
            f"回复风格：{style}（{style_hint}）\n"
        )
        resp = await self.context.llm_generate(chat_provider_id=provider_id, prompt=prompt)
        text = (getattr(resp, "completion_text", "") or "").strip()
        if not text:
            raise RuntimeError("LLM returned empty reply")
        return self._clean_reply(text)

    def _clean_reply(self, text: str) -> str:
        text = re.sub(r"^\s*(回复|答复|输出|评论回复)\s*[:：]\s*", "", text.strip())
        text = text.strip().strip("\"'“”‘’")
        text = re.sub(r"\s+", " ", text)
        return text[:200]
