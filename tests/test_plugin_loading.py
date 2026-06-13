import tempfile
import unittest
from pathlib import Path
import base64

import main as plugin_main


class DummyContext:
    async def send_message(self, *_args, **_kwargs):
        return None


class FailingQrClient:
    async def create_qrcode_login(self):
        raise RuntimeError("network down")

    async def aclose(self):
        return None


class TestPluginLoading(unittest.IsolatedAsyncioTestCase):
    async def test_plugin_instantiates_before_startup_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = plugin_main.get_astrbot_data_path
            plugin_main.get_astrbot_data_path = lambda: Path(tmp)
            try:
                plugin = plugin_main.BilibiliAssistantPlugin(DummyContext(), {"bilibili_cookie": ""})
                self.assertIsNone(plugin._init_task)
                await plugin._ready()
                self.assertIsNotNone(plugin._init_task)
                self.assertTrue(plugin.db_path.exists())
                await plugin.terminate()
            finally:
                plugin_main.get_astrbot_data_path = original

    async def test_qrcode_create_returns_json_error_without_http_500(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = plugin_main.get_astrbot_data_path
            plugin_main.get_astrbot_data_path = lambda: Path(tmp)
            try:
                plugin = plugin_main.BilibiliAssistantPlugin(DummyContext(), {"bilibili_cookie": ""})
                plugin.client = FailingQrClient()
                response = await plugin.page_qrcode_create()
                self.assertFalse(response["ok"])
                self.assertIn("network down", response["message"])
                await plugin.terminate()
            finally:
                plugin_main.get_astrbot_data_path = original

    async def test_qrcode_image_is_png_data_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = plugin_main.get_astrbot_data_path
            plugin_main.get_astrbot_data_path = lambda: Path(tmp)
            try:
                plugin = plugin_main.BilibiliAssistantPlugin(DummyContext(), {"bilibili_cookie": ""})
                data_url = plugin._qr_png_data_url("https://passport.bilibili.com/test")
                self.assertTrue(data_url.startswith("data:image/png;base64,"))
                raw = base64.b64decode(data_url.split(",", 1)[1])
                self.assertTrue(raw.startswith(b"\x89PNG\r\n\x1a\n"))
                await plugin.terminate()
            finally:
                plugin_main.get_astrbot_data_path = original

    async def test_help_text_contains_full_command_tutorial(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = plugin_main.get_astrbot_data_path
            plugin_main.get_astrbot_data_path = lambda: Path(tmp)
            try:
                plugin = plugin_main.BilibiliAssistantPlugin(DummyContext(), {"bilibili_cookie": ""})
                help_text = plugin._help_text()
                self.assertIn("/bilihelp", help_text)
                self.assertIn("/bili_ai_reply [风格] <需要回复的内容>", help_text)
                self.assertIn("/bili_ai_rpid <BV号> <rpid> [风格]", help_text)
                self.assertIn("/bili_ai_check", help_text)
                self.assertIn("/bili_comments <BV号> [数量]", help_text)
                self.assertIn("/bili_draft <BV号> <rpid> [风格]", help_text)
                self.assertIn("/bili_monitor_add <BV号>", help_text)
                self.assertIn("/bili_logs_export [数量]", help_text)
                await plugin.terminate()
            finally:
                plugin_main.get_astrbot_data_path = original
