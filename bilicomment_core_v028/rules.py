from __future__ import annotations

from .models import Comment


class RuleEngine:
    THANKS = ("好看", "支持", "喜欢", "三连", "爱了", "不错", "赞")
    QUESTION = ("?", "？", "怎么", "为什么", "在哪", "哪里", "如何")
    UPDATE = ("更新", "下一期", "快更", "催更", "续集")
    FEEDBACK = ("错误", "不对", "bug", "BUG", "问题", "修复")
    NEGATIVE = ("不好", "失望", "难受", "看不懂", "太差")

    def classify(self, comment: Comment) -> str:
        text = comment.message
        if any(word in text for word in self.FEEDBACK):
            return "feedback"
        if any(word in text for word in self.NEGATIVE):
            return "negative"
        if any(word in text for word in self.QUESTION):
            return "question"
        if any(word in text for word in self.UPDATE):
            return "update"
        if any(word in text for word in self.THANKS):
            return "thanks"
        return "general"

    def template_reply(self, comment: Comment, style: str = "friendly") -> str:
        kind = self.classify(comment)
        prefix = self._style_prefix(style)
        if kind == "thanks":
            return f"{prefix}感谢支持，我会继续认真做内容。"
        if kind == "question":
            return f"{prefix}这个问题我看到了，后面会尽量补充说明。"
        if kind == "update":
            return f"{prefix}已经记下啦，后续会继续安排相关内容。"
        if kind == "feedback":
            return f"{prefix}感谢提醒，我会检查一下这个问题。"
        if kind == "negative":
            return f"{prefix}谢谢反馈，我会再看看哪里能改得更清楚。"
        return f"{prefix}谢谢你的评论，我看到了。"

    def _style_prefix(self, style: str) -> str:
        if style == "official":
            return ""
        if style == "cute":
            return "嘿嘿，"
        if style == "concise":
            return ""
        if style == "humorous":
            return "收到，这条我先端走研究一下，"
        return ""
