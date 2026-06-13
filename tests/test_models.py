import unittest

from bilicomment_core.models import Comment, ReplyDraft


class TestModels(unittest.TestCase):
    def test_comment_from_bili(self):
        item = {
            "rpid": 123,
            "root": 0,
            "parent": 0,
            "ctime": 100,
            "like": 5,
            "rcount": 2,
            "member": {"mid": "42", "uname": "tester"},
            "content": {"message": "好看，支持"},
        }
        comment = Comment.from_bili(item, oid=999, type_=1)
        self.assertEqual(comment.rpid, 123)
        self.assertEqual(comment.oid, 999)
        self.assertEqual(comment.mid, 42)
        self.assertEqual(comment.message, "好看，支持")
        self.assertFalse(comment.is_thread_reply)
        self.assertEqual(comment.level_label, "主评论")
        self.assertEqual(comment.reply_root, 123)
        self.assertEqual(comment.reply_parent, 123)

    def test_nested_comment_level(self):
        item = {
            "rpid": 456,
            "root": 123,
            "parent": 123,
            "ctime": 100,
            "like": 1,
            "rcount": 0,
            "member": {"mid": "43", "uname": "reply-user"},
            "content": {"message": "这是评论的评论"},
        }
        comment = Comment.from_bili(item, oid=999, type_=1)
        self.assertTrue(comment.is_thread_reply)
        self.assertEqual(comment.level_label, "评论回复")
        self.assertEqual(comment.reply_root, 123)
        self.assertEqual(comment.reply_parent, 456)

    def test_reply_draft_new(self):
        draft = ReplyDraft.new(
            oid=1,
            type=1,
            target_rpid=2,
            root=2,
            parent=2,
            source_comment="hello",
            reply_text="thanks",
            safety_flags=["manual_review"],
        )
        self.assertTrue(draft.draft_id.startswith("draft_"))
        self.assertEqual(draft.status, "pending")
        self.assertEqual(draft.safety_flags, ["manual_review"])


if __name__ == "__main__":
    unittest.main()
