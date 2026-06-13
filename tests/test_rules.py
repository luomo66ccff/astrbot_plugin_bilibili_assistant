import unittest

from bilicomment_core.models import Comment
from bilicomment_core.rules import RuleEngine


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


class TestRules(unittest.TestCase):
    def test_classify_thanks(self):
        self.assertEqual(RuleEngine().classify(make_comment("太好看了，三连支持")), "thanks")

    def test_classify_question(self):
        self.assertEqual(RuleEngine().classify(make_comment("这个怎么做？")), "question")

    def test_template_reply(self):
        reply = RuleEngine().template_reply(make_comment("快更新"), "friendly")
        self.assertIn("后续", reply)

    def test_classify_negative(self):
        self.assertEqual(RuleEngine().classify(make_comment("这期有点看不懂")), "negative")


if __name__ == "__main__":
    unittest.main()
