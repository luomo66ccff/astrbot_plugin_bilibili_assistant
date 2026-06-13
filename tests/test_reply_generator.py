import unittest

from bilicomment_core.models import Comment
from bilicomment_core.reply_generator import ReplyGenerator
from bilicomment_core.rules import RuleEngine


class DummyLlmResponse:
    completion_text = "回复：谢谢喜欢，我会继续认真做下一期内容。"


class DummyLlmContext:
    def __init__(self):
        self.calls = []

    async def llm_generate(self, **kwargs):
        self.calls.append(kwargs)
        return DummyLlmResponse()


class FailingLlmContext:
    async def llm_generate(self, **kwargs):
        raise RuntimeError("model missing")


def make_comment(text: str) -> Comment:
    return Comment(
        rpid=1,
        oid=1,
        type=1,
        root=0,
        parent=0,
        mid=1,
        uname="u",
        message=text,
        ctime=0,
        like=0,
        replies_count=0,
    )


class TestReplyGenerator(unittest.IsolatedAsyncioTestCase):
    async def test_generate_uses_llm_and_cleans_reply_prefix(self):
        context = DummyLlmContext()
        generator = ReplyGenerator(context=context, rules=RuleEngine())

        reply = await generator.generate(
            video_title="测试视频",
            comment=make_comment("太好看了，三连支持"),
            style="friendly",
            chat_provider_id="provider-1",
        )

        self.assertEqual(reply, "谢谢喜欢，我会继续认真做下一期内容。")
        self.assertEqual(context.calls[0]["chat_provider_id"], "provider-1")
        self.assertIn("评论分类：thanks", context.calls[0]["prompt"])

    async def test_generate_from_text_builds_comment_context(self):
        context = DummyLlmContext()
        generator = ReplyGenerator(context=context, rules=RuleEngine())

        reply = await generator.generate_from_text("这个地方是不是讲错了？", style="official")

        self.assertIn("谢谢喜欢", reply)
        self.assertIn("这个地方是不是讲错了？", context.calls[0]["prompt"])

    async def test_generate_records_template_fallback_reason(self):
        generator = ReplyGenerator(context=FailingLlmContext(), rules=RuleEngine())

        reply = await generator.generate_from_text("太好看了", style="friendly")

        self.assertEqual(generator.last_source, "template")
        self.assertIn("model missing", generator.last_error)
        self.assertIn("感谢支持", reply)


if __name__ == "__main__":
    unittest.main()
