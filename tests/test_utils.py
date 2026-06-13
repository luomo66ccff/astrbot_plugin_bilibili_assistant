import unittest

from bilicomment_core.utils import sanitize_plain_text, summarize_text


class TestUtils(unittest.TestCase):
    def test_sanitize_plain_text_replaces_image_markup(self):
        text = "看图 ![x](https://example.com/a.jpg) [CQ:image,file=b.png] <img src='x.png'>"
        cleaned = sanitize_plain_text(text)
        self.assertNotIn("![", cleaned)
        self.assertNotIn("[CQ:image", cleaned)
        self.assertNotIn("<img", cleaned)
        self.assertIn("[图片]", cleaned)

    def test_summarize_text_replaces_image_urls(self):
        summary = summarize_text("图片 https://example.com/a.png?x=1", 80)
        self.assertIn("[图片链接]", summary)
        self.assertNotIn("https://example.com", summary)
