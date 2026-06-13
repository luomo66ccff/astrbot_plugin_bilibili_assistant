import httpx
import unittest

from bilicomment_core.bilibili_client import BilibiliClient


class TestBilibiliClient(unittest.TestCase):
    def test_cookie_header_from_response_keeps_login_fields(self):
        response = httpx.Response(
            200,
            headers=[
                ("set-cookie", "SESSDATA=abc; Domain=.bilibili.com; Path=/; HttpOnly"),
                ("set-cookie", "bili_jct=csrf; Domain=.bilibili.com; Path=/"),
                ("set-cookie", "DedeUserID=123; Domain=.bilibili.com; Path=/"),
                ("set-cookie", "sid=xyz; Domain=.bilibili.com; Path=/"),
            ],
        )

        cookie = BilibiliClient.cookie_header_from_response(response)

        self.assertIn("SESSDATA=abc", cookie)
        self.assertIn("bili_jct=csrf", cookie)
        self.assertIn("DedeUserID=123", cookie)
        self.assertIn("sid=xyz", cookie)

    def test_comments_from_items_flattens_nested_replies(self):
        client = BilibiliClient(cookie="")
        items = [
            {
                "rpid": 100,
                "root": 0,
                "parent": 0,
                "ctime": 1,
                "like": 3,
                "rcount": 1,
                "member": {"mid": "1", "uname": "root-user"},
                "content": {"message": "主评论"},
                "replies": [
                    {
                        "rpid": 101,
                        "root": 100,
                        "parent": 100,
                        "ctime": 2,
                        "like": 0,
                        "rcount": 0,
                        "member": {"mid": "2", "uname": "child-user"},
                        "content": {"message": "评论回复"},
                    }
                ],
            }
        ]

        comments = client._comments_from_items(items, oid=999, type_=1)

        self.assertEqual([item.rpid for item in comments], [100, 101])
        self.assertEqual(comments[0].level_label, "主评论")
        self.assertEqual(comments[1].level_label, "评论回复")
        self.assertEqual(comments[1].reply_root, 100)
        self.assertEqual(comments[1].reply_parent, 101)
