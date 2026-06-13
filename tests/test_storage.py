import tempfile
import unittest
from pathlib import Path

from bilicomment_core.models import Comment, MonitorTask
from bilicomment_core.storage import Storage


class TestStorage(unittest.IsolatedAsyncioTestCase):
    async def test_monitor_task_crud(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "test.sqlite3")
            await storage.init()
            task = MonitorTask.new(
                bvid="BV123",
                aid=456,
                title="demo",
                interval_seconds=300,
                mode="draft",
                created_by="user",
                notify_origin="origin",
            )
            await storage.add_monitor_task(task)

            tasks = await storage.list_monitor_tasks()
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].task_id, task.task_id)
            self.assertEqual(tasks[0].notify_origin, "origin")

            await storage.set_monitor_enabled(task.task_id, False)
            paused = await storage.get_monitor_task(task.task_id)
            self.assertFalse(paused.enabled)

            await storage.update_monitor_progress(
                task.task_id,
                last_checked_at=100,
                last_seen_rpid=999,
            )
            updated = await storage.get_monitor_task(task.task_id)
            self.assertEqual(updated.last_checked_at, 100)
            self.assertEqual(updated.last_seen_rpid, 999)

            removed = await storage.remove_monitor_task(task.task_id)
            self.assertTrue(removed)
            self.assertEqual(await storage.list_monitor_tasks(), [])

    async def test_blacklist_crud(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "test.sqlite3")
            await storage.init()
            await storage.add_blacklisted_user("123", "spam")
            self.assertTrue(await storage.is_user_blacklisted("123"))
            rows = await storage.list_blacklisted_users()
            self.assertEqual(rows[0][0], "123")
            self.assertEqual(rows[0][1], "spam")
            self.assertTrue(await storage.remove_blacklisted_user("123"))
            self.assertFalse(await storage.is_user_blacklisted("123"))

    async def test_seen_comment_preserves_nested_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "test.sqlite3")
            await storage.init()
            comment = Comment(
                rpid=101,
                oid=999,
                type=1,
                root=100,
                parent=100,
                mid=2,
                uname="child-user",
                message="评论回复",
                ctime=10,
                like=4,
                replies_count=0,
            )
            await storage.save_seen_comment(comment)

            stored = await storage.get_seen_comment(101)

            self.assertIsNotNone(stored)
            self.assertTrue(stored.is_thread_reply)
            self.assertEqual(stored.root, 100)
            self.assertEqual(stored.parent, 100)
            self.assertEqual(stored.reply_parent, 101)
            self.assertEqual(stored.like, 4)


if __name__ == "__main__":
    unittest.main()
