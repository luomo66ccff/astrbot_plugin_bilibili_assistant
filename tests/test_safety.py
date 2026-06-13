import unittest

from bilicomment_core.safety import SafetyChecker


class FakeStorage:
    async def has_replied_to_comment(self, target_rpid: int) -> bool:
        return target_rpid == 99

    async def is_user_blacklisted(self, mid: int | str) -> bool:
        return str(mid) == "123"

    async def has_recent_reply_to_user(self, mid: int | str, cooldown_seconds: int = 600) -> bool:
        return str(mid) == "777"

    async def recent_reply_texts(self, limit: int = 20):
        return ["感谢支持，我会继续认真做内容。"]

    async def count_logs_since(self, since_ts: int, success_only: bool = True) -> int:
        return 0


class TestSafety(unittest.IsolatedAsyncioTestCase):
    async def test_empty_blocked(self):
        checker = SafetyChecker(FakeStorage(), [], 5, 30)
        result = await checker.check_reply_text("", oid=1, target_rpid=1, mid=1)
        self.assertFalse(result.allowed)
        self.assertIn("empty", result.flags)

    async def test_ad_blocked(self):
        checker = SafetyChecker(FakeStorage(), [], 5, 30)
        result = await checker.check_reply_text("加微信私聊返钱", oid=1, target_rpid=1, mid=1)
        self.assertFalse(result.allowed)
        self.assertIn("ad", result.flags)

    async def test_duplicate_target_blocked(self):
        checker = SafetyChecker(FakeStorage(), [], 5, 30)
        result = await checker.check_reply_text("谢谢提醒，我看一下。", oid=1, target_rpid=99, mid=1)
        self.assertFalse(result.allowed)
        self.assertIn("duplicate_target", result.flags)

    async def test_user_cooldown_blocked(self):
        checker = SafetyChecker(FakeStorage(), [], 5, 30)
        result = await checker.check_reply_text("谢谢提醒，我看一下。", oid=1, target_rpid=1, mid=777)
        self.assertFalse(result.allowed)
        self.assertIn("user_cooldown", result.flags)

    async def test_blacklisted_source_flagged(self):
        from bilicomment_core.models import Comment

        checker = SafetyChecker(FakeStorage(), [], 5, 30)
        result = await checker.check_source_comment(
            Comment(
                rpid=1,
                oid=1,
                type=1,
                root=0,
                parent=0,
                mid=123,
                uname="blocked",
                message="普通评论",
                ctime=0,
                like=0,
                replies_count=0,
            )
        )
        self.assertTrue(result.allowed)
        self.assertIn("blacklisted_user", result.flags)


if __name__ == "__main__":
    unittest.main()
