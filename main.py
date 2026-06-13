import asyncio
import base64
import csv
import inspect
import secrets
import struct
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional
import zlib

try:
    from astrbot.api import logger
    from astrbot.api.event import AstrMessageEvent, MessageChain, filter
    from astrbot.api.star import Context, Star
    from astrbot.core.utils.astrbot_path import get_astrbot_data_path
except ModuleNotFoundError:
    class _DummyLogger:
        def warning(self, *_args, **_kwargs):
            pass

        def error(self, *_args, **_kwargs):
            pass

    class _DummyFilter:
        def command(self, *_args, **_kwargs):
            def deco(func):
                return func

            return deco

        def on_astrbot_loaded(self, *_args, **_kwargs):
            def deco(func):
                return func

            return deco

    class Star:
        def __init__(self, context):
            self.context = context

    class Context:
        pass

    class AstrMessageEvent:
        pass

    class MessageChain:
        def message(self, text):
            return text

    def get_astrbot_data_path():
        return Path(__file__).resolve().parent

    logger = _DummyLogger()
    filter = _DummyFilter()

PLUGIN_DIR = Path(__file__).resolve().parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

def _purge_package_cache(package_name: str) -> None:
    for module_name in list(sys.modules):
        if module_name == package_name or module_name.startswith(package_name + "."):
            sys.modules.pop(module_name, None)


try:
    from bilicomment_core_v028.bilibili_client import BiliApiError, BilibiliClient
    from bilicomment_core_v028.models import Comment, MonitorTask, ReplyDraft
    from bilicomment_core_v028.reply_generator import ReplyGenerator
    from bilicomment_core_v028.rules import RuleEngine
    from bilicomment_core_v028.safety import SafetyChecker
    from bilicomment_core_v028.scheduler import MonitorScheduler
    from bilicomment_core_v028.storage import Storage
    from bilicomment_core_v028.utils import now_ts, safe_int, summarize_text

    CORE_PACKAGE = "bilicomment_core_v028"
except ModuleNotFoundError as exc:
    if not str(getattr(exc, "name", "")).startswith("bilicomment_core_v028"):
        raise
    _purge_package_cache("bilicomment_core")
    from bilicomment_core.bilibili_client import BiliApiError, BilibiliClient
    from bilicomment_core.models import Comment, MonitorTask, ReplyDraft
    from bilicomment_core.reply_generator import ReplyGenerator
    from bilicomment_core.rules import RuleEngine
    from bilicomment_core.safety import SafetyChecker
    from bilicomment_core.scheduler import MonitorScheduler
    from bilicomment_core.storage import Storage
    from bilicomment_core.utils import now_ts, safe_int, summarize_text

    CORE_PACKAGE = "bilicomment_core"
    logger.warning("bilicomment_core_v028 not found; loaded fallback bilicomment_core.")


PLUGIN_NAME = "astrbot_plugin_bilibili_assistant"
PLUGIN_VERSION = "v0.2.13"


class BilibiliAssistantPlugin(Star):
    def __init__(self, context: Context, config: Optional[Dict[str, Any]] = None):
        super().__init__(context)
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))
        self.dry_run = bool(self.config.get("dry_run", True))
        self.auto_reply_enabled = bool(self.config.get("auto_reply_enabled", False))
        self.require_confirmation = bool(self.config.get("require_confirmation", True))
        self.reply_style = str(self.config.get("reply_style", "friendly"))
        self.admin_user_ids = {str(x) for x in self.config.get("admin_user_ids", []) if str(x)}
        self.allowed_video_list = {
            str(x).strip() for x in self.config.get("allowed_video_list", []) if str(x).strip()
        }
        self.config_blacklisted_user_ids = {
            str(x).strip() for x in self.config.get("blacklisted_user_ids", []) if str(x).strip()
        }
        self.default_check_interval = max(
            safe_int(self.config.get("default_check_interval_seconds"), 300),
            60,
        )
        self.cookie = str(self.config.get("bilibili_cookie", "") or "")
        self.data_dir = self._data_dir()
        self.db_path = self.data_dir / "bilibili_assistant.sqlite3"
        self.client = BilibiliClient(cookie=self.cookie)
        self.storage = Storage(self.db_path)
        self.rules = RuleEngine()
        self.safety = SafetyChecker(
            storage=self.storage,
            blocked_keywords=list(self.config.get("blocked_keywords", [])),
            max_replies_per_hour=safe_int(self.config.get("max_replies_per_hour"), 5),
            max_replies_per_day=safe_int(self.config.get("max_replies_per_day"), 30),
        )
        self.generator = ReplyGenerator(
            context=self.context,
            rules=self.rules,
            default_style=self.reply_style,
            chat_provider_id=str(self.config.get("chat_provider_id", "") or "") or None,
        )
        self.confirm_codes: Dict[str, Dict[str, Any]] = {}
        self.scheduler = MonitorScheduler(
            storage=self.storage,
            client=self.client,
            generator=self.generator,
            safety=self.safety,
            notify=self._notify,
            auto_reply_enabled=lambda: self.auto_reply_enabled,
            dry_run=lambda: self.dry_run,
            require_confirmation=lambda: self.require_confirmation,
        )
        self._register_web_apis()
        self._init_task: Optional[asyncio.Task] = None

    @filter.command("bilicomment_on")
    async def bilicomment_on(self, event: AstrMessageEvent):
        """启用插件总开关。"""
        if not self._is_admin(event):
            yield event.plain_result("你没有权限启用插件，请联系管理员配置 admin_user_ids。")
            return
        self.enabled = True
        yield event.plain_result("B站评论助手已在当前运行实例中启用。")

    @filter.command("bilicomment_off")
    async def bilicomment_off(self, event: AstrMessageEvent):
        """关闭插件总开关。"""
        if not self._is_admin(event):
            yield event.plain_result("你没有权限关闭插件，请联系管理员配置 admin_user_ids。")
            return
        self.enabled = False
        yield event.plain_result("B站评论助手已在当前运行实例中关闭。")

    @filter.command("bilicomment_status")
    async def bilicomment_status(self, event: AstrMessageEvent):
        """查看插件总开关状态。"""
        yield event.plain_result(await self._status_text(include_account=False))

    @filter.command("bili_version")
    async def bili_version(self, event: AstrMessageEvent):
        """查看当前 AstrBot 实际加载的插件版本。"""
        yield event.plain_result(self._version_text())

    @filter.command("bili_status")
    async def bili_status(self, event: AstrMessageEvent):
        """检查插件状态和 B站登录状态。"""
        await self._ready()
        if not self.enabled:
            yield event.plain_result("插件当前未启用，请先使用 /bilicomment_on。")
            return
        yield event.plain_result(await self._status_text(include_account=True))

    @filter.command("bili_bind")
    async def bili_bind(self, event: AstrMessageEvent):
        """提示用户去配置中填写 Cookie。"""
        yield event.plain_result(
            "请在插件配置页填写 bilibili_cookie。Cookie 是敏感凭证，不建议在聊天里发送。"
        )

    @filter.command("bili_video")
    async def bili_video(self, event: AstrMessageEvent, bvid: str):
        """查询视频基本信息。"""
        if not self.enabled:
            yield event.plain_result("插件当前未启用，请先使用 /bilicomment_on。")
            return
        try:
            info = await self.client.get_video_info_by_bvid(bvid)
        except Exception as exc:
            yield event.plain_result(f"{self._friendly_error(exc)}\n\n{self._version_text()}")
            return
        yield event.plain_result(
            "\n".join(
                [
                    f"标题：{info.get('title', '-')}",
                    f"aid：{info.get('aid', '-')}",
                    f"bvid：{info.get('bvid', bvid)}",
                    f"UP主：{info.get('owner', {}).get('name', '-')}",
                    "评论区：oid=aid, type=1",
                ]
            )
        )

    @filter.command("bili_comments")
    async def bili_comments(self, event: AstrMessageEvent, bvid: str, count: int = 5):
        """拉取某视频最新评论。"""
        await self._ready()
        if not self.enabled:
            yield event.plain_result("插件当前未启用，请先使用 /bilicomment_on。")
            return
        try:
            info = await self.client.get_video_info_by_bvid(bvid)
            comments = await self._get_replies(
                oid=int(info["aid"]),
                type_=1,
                page=1,
                sort=1,
                bvid=str(info.get("bvid") or bvid),
            )
            for comment in comments:
                await self.storage.save_seen_comment(comment)
        except Exception as exc:
            yield event.plain_result(self._friendly_error(exc))
            return
        max_count = max(1, min(int(count), 10))
        lines = [f"{info.get('title', bvid)} 最近评论："]
        for index, comment in enumerate(comments[:max_count], 1):
            indent = "  ↳ " if comment.is_thread_reply else ""
            relation = (
                f" | root={comment.root} | parent={comment.parent}"
                if comment.is_thread_reply
                else f" | 回复数={comment.replies_count}"
            )
            lines.append(
                f"{indent}{index}. 【{comment.level_label}】{comment.uname}(mid={comment.mid}) "
                f"| rpid={comment.rpid}{relation} | 赞={comment.like} | "
                f"{summarize_text(comment.message, 60)}"
            )
        lines.append("可用 /bili_draft <BV号> <rpid> 生成回复草稿。")
        yield event.plain_result("\n".join(lines))

    @filter.command("bili_draft")
    async def bili_draft(self, event: AstrMessageEvent, bvid: str, rpid: int, style: str = ""):
        """针对某条评论生成回复草稿。"""
        await self._ready()
        if not self._is_admin(event):
            yield event.plain_result("你没有权限执行这个操作。")
            return
        try:
            info = await self.client.get_video_info_by_bvid(bvid)
            comment = await self._find_comment(
                int(info["aid"]),
                int(rpid),
                bvid=str(info.get("bvid") or bvid),
            )
            if comment is None:
                yield event.plain_result("没有找到这条评论，请先使用 /bili_comments 拉取最新评论。")
                return
            safety = await self.safety.check_source_comment(comment)
            reply_text = await self.generator.generate(
                video_title=str(info.get("title", "")),
                comment=comment,
                style=style or self.reply_style,
                chat_provider_id=await self._current_chat_provider_id(event),
            )
            send_safety = await self.safety.check_reply_text(
                reply_text=reply_text,
                oid=comment.oid,
                target_rpid=comment.rpid,
                mid=comment.mid,
            )
            flags = sorted(set(safety.flags + send_safety.flags))
            draft = ReplyDraft.new(
                oid=comment.oid,
                type=comment.type,
                target_rpid=comment.rpid,
                target_mid=comment.mid,
                root=comment.reply_root,
                parent=comment.reply_parent,
                source_comment=comment.message,
                reply_text=reply_text,
                safety_flags=flags,
            )
            await self.storage.create_reply_draft(draft)
        except Exception as exc:
            yield event.plain_result(self._friendly_error(exc))
            return
        yield event.plain_result(
            "\n".join(
                [
                    f"已生成草稿：{draft.draft_id}",
                    f"目标层级：{comment.level_label}（root={draft.root}, parent={draft.parent}）",
                    self._generation_note(),
                    f"安全标记：{', '.join(flags) if flags else '无'}",
                    f"内容：{draft.reply_text}",
                    f"发送：/bili_send {draft.draft_id}",
                    f"修改：/bili_edit {draft.draft_id} 新内容",
                ]
            )
        )

    @filter.command("bili_ai_rpid")
    async def bili_ai_rpid(self, event: AstrMessageEvent, bvid: str, rpid: int, style: str = ""):
        """根据 BV 号和评论 rpid 调用 AI 生成回复，不保存草稿。"""
        await self._ready()
        if not self.enabled:
            yield event.plain_result("插件当前未启用，请先使用 /bilicomment_on。")
            return
        try:
            info = await self.client.get_video_info_by_bvid(bvid)
            comment = await self._find_comment(
                int(info["aid"]),
                int(rpid),
                bvid=str(info.get("bvid") or bvid),
            )
            if comment is None:
                yield event.plain_result("没有找到这条评论，请先使用 /bili_comments 拉取最新评论。")
                return
            reply_text = await self.generator.generate(
                video_title=str(info.get("title", "")),
                comment=comment,
                style=style or self.reply_style,
                chat_provider_id=await self._current_chat_provider_id(event),
            )
            safety = await self.safety.check_reply_text(
                reply_text=reply_text,
                oid=comment.oid,
                target_rpid=comment.rpid,
                mid=comment.mid,
            )
        except Exception as exc:
            yield event.plain_result(self._friendly_error(exc))
            return
        flags = "、".join(safety.flags) if safety.flags else "无"
        yield event.plain_result(
            "\n".join(
                [
                    "AI 已根据 rpid 生成回复：",
                    f"视频：{info.get('title', bvid)}",
                    f"目标层级：{comment.level_label}",
                    f"目标 rpid：{comment.rpid}",
                    f"原评论：{summarize_text(comment.message, 120)}",
                    self._generation_note(),
                    f"安全检查：{'通过' if safety.allowed else '未通过'}",
                    f"安全标记：{flags}",
                    f"回复：{reply_text}",
                    "",
                    f"保存为草稿：/bili_draft {bvid} {rpid} {style or self.reply_style}",
                    "提示：本命令只生成文本，不会保存草稿，也不会发布到 B站。",
                ]
            )
        )

    @filter.command("bili_ai_reply")
    async def bili_ai_reply(self, event: AstrMessageEvent):
        """根据输入内容用 AI 生成一条评论区回复。"""
        await self._ready()
        if not self.enabled:
            yield event.plain_result("插件当前未启用，请先使用 /bilicomment_on。")
            return
        raw = self._tail_after_args(event.message_str, 1)
        style, content = self._split_style_and_content(raw)
        if not content:
            yield event.plain_result(
                "用法：/bili_ai_reply [friendly|official|cute|concise|humorous] <需要回复的内容>"
            )
            return
        try:
            reply_text = await self.generator.generate_from_text(
                content,
                style=style,
                chat_provider_id=await self._current_chat_provider_id(event),
            )
            safety = await self.safety.check_reply_text(
                reply_text=reply_text,
                oid=0,
                target_rpid=0,
                mid=0,
            )
        except Exception as exc:
            yield event.plain_result(self._friendly_error(exc))
            return
        flags = "、".join(safety.flags) if safety.flags else "无"
        lines = [
            "AI 回复草稿：",
            reply_text,
            "",
            f"风格：{style}",
            self._generation_note(),
            f"安全检查：{'通过' if safety.allowed else '未通过'}",
            f"安全标记：{flags}",
            "提示：这是试写文本，不会自动发布到 B站。",
        ]
        yield event.plain_result("\n".join(lines))

    @filter.command("bili_ai_check")
    async def bili_ai_check(self, event: AstrMessageEvent):
        """测试插件能否调用 AstrBot 当前会话模型。"""
        provider_id = await self._current_chat_provider_id(event)
        try:
            resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt="请只回复：AI_OK",
            )
            text = (getattr(resp, "completion_text", "") or "").strip()
        except Exception as exc:
            yield event.plain_result(
                "\n".join(
                    [
                        "AI 调用失败，当前会退回固定模板。",
                        f"provider_id：{provider_id or '-'}",
                        f"错误：{exc}",
                        "请检查 AstrBot 是否配置了可用模型，或在插件配置里填写 chat_provider_id。",
                    ]
                )
            )
            return
        yield event.plain_result(
            "\n".join(
                [
                    "AI 调用成功。",
                    f"provider_id：{provider_id or '默认/当前会话'}",
                    f"模型返回：{text or '-'}",
                ]
            )
        )

    @filter.command("bili_send")
    async def bili_send(self, event: AstrMessageEvent, draft_id: str):
        """发送已经生成的草稿，dry_run 默认不实际发送。"""
        await self._ready()
        if not self._is_admin(event):
            yield event.plain_result("你没有权限执行这个操作。")
            return
        draft = await self.storage.get_reply_draft(draft_id)
        if draft is None:
            yield event.plain_result("没有找到这个草稿。")
            return
        if draft.status != "pending":
            yield event.plain_result(f"草稿状态是 {draft.status}，不能发送。")
            return
        if self.dry_run:
            yield event.plain_result(await self._send_draft(draft))
            return
        if self.require_confirmation:
            code = secrets.token_hex(3)
            self.confirm_codes[code] = {
                "draft_id": draft.draft_id,
                "expires_at": int(time.time()) + 300,
                "sender_id": self._sender_id(event),
            }
            yield event.plain_result(
                "\n".join(
                    [
                        "发送前需要二次确认。",
                        f"草稿：{draft.reply_text}",
                        f"确认码：{code}",
                        f"5分钟内发送 /bili_confirm {code} 才会继续。",
                    ]
                )
            )
            return
        yield event.plain_result(await self._send_draft(draft))

    @filter.command("bili_confirm")
    async def bili_confirm(self, event: AstrMessageEvent, confirm_code: str):
        """确认发送草稿。"""
        await self._ready()
        if not self._is_admin(event):
            yield event.plain_result("你没有权限执行这个操作。")
            return
        payload = self.confirm_codes.get(confirm_code)
        if not payload:
            yield event.plain_result("确认码不存在或已经使用。")
            return
        if payload["expires_at"] < int(time.time()):
            self.confirm_codes.pop(confirm_code, None)
            yield event.plain_result("确认码已过期，请重新执行 /bili_send。")
            return
        if payload.get("sender_id") and payload["sender_id"] != self._sender_id(event):
            yield event.plain_result("确认码只能由发起发送的人使用。")
            return
        self.confirm_codes.pop(confirm_code, None)
        if payload.get("action") == "delete_reply":
            yield event.plain_result(await self._delete_reply_confirmed(payload))
            return
        draft = await self.storage.get_reply_draft(payload["draft_id"])
        if draft is None:
            yield event.plain_result("确认码对应的草稿不存在。")
            return
        yield event.plain_result(await self._send_draft(draft))

    @filter.command("bili_dryrun")
    async def bili_dryrun(self, event: AstrMessageEvent, mode: str):
        """打开或关闭演练模式。"""
        await self._ready()
        if not self._is_admin(event):
            yield event.plain_result("你没有权限执行这个操作。")
            return
        value = mode.strip().lower()
        if value not in {"on", "off"}:
            yield event.plain_result("用法：/bili_dryrun on 或 /bili_dryrun off")
            return
        if value == "off" and self.require_confirmation:
            self.dry_run = False
            yield event.plain_result("dry_run 已关闭；require_confirmation 仍开启，发送前需要 /bili_confirm。")
            return
        self.dry_run = value == "on"
        yield event.plain_result(f"dry_run 已设置为：{self.dry_run}")

    @filter.command("bili_monitor_add")
    async def bili_monitor_add(
        self,
        event: AstrMessageEvent,
        bvid: str,
        mode: str = "draft",
        interval_seconds: int = 0,
    ):
        """添加监听任务。"""
        await self._ready()
        if not self._is_admin(event):
            yield event.plain_result("你没有权限执行这个操作。")
            return
        mode = (mode or "draft").strip()
        if mode not in {"notify_only", "draft", "auto_reply"}:
            yield event.plain_result("模式只能是 notify_only、draft 或 auto_reply。")
            return
        if mode == "auto_reply" and not self.auto_reply_enabled:
            yield event.plain_result("配置中的 auto_reply_enabled=false，不能添加 auto_reply 任务。")
            return
        if self.allowed_video_list and bvid not in self.allowed_video_list:
            yield event.plain_result("该 BV 号不在 allowed_video_list 中，不能主动监听。")
            return
        interval = max(safe_int(interval_seconds, self.default_check_interval), 60)
        try:
            info = await self.client.get_video_info_by_bvid(bvid)
            task = MonitorTask.new(
                bvid=str(info.get("bvid") or bvid),
                aid=int(info["aid"]),
                title=str(info.get("title") or bvid),
                interval_seconds=interval,
                mode=mode,
                created_by=self._sender_id(event),
                notify_origin=self._origin(event),
            )
            await self.storage.add_monitor_task(task)
            await self.scheduler.start()
        except Exception as exc:
            yield event.plain_result(self._friendly_error(exc))
            return
        yield event.plain_result(
            f"已添加监听任务 {task.task_id}：{task.title}，模式 {mode}，间隔 {interval} 秒。"
        )

    @filter.command("bili_monitor_list")
    async def bili_monitor_list(self, event: AstrMessageEvent):
        """列出监听任务。"""
        await self._ready()
        if not self._is_admin(event):
            yield event.plain_result("你没有权限执行这个操作。")
            return
        tasks = await self.storage.list_monitor_tasks(include_disabled=True)
        if not tasks:
            yield event.plain_result("暂无监听任务。")
            return
        lines = ["监听任务："]
        for task in tasks[:20]:
            enabled = "启用" if task.enabled else "暂停"
            lines.append(
                f"{task.task_id} | {enabled} | {task.mode} | {task.interval_seconds}s | "
                f"{task.bvid} | {summarize_text(task.title, 30)} | last={task.last_checked_at or '-'}"
            )
        yield event.plain_result("\n".join(lines))

    @filter.command("bili_monitor_pause")
    async def bili_monitor_pause(self, event: AstrMessageEvent, task_id: str):
        """暂停监听任务。"""
        await self._ready()
        if not self._is_admin(event):
            yield event.plain_result("你没有权限执行这个操作。")
            return
        await self.storage.set_monitor_enabled(task_id, False)
        yield event.plain_result(f"已暂停监听任务：{task_id}")

    @filter.command("bili_monitor_resume")
    async def bili_monitor_resume(self, event: AstrMessageEvent, task_id: str):
        """恢复监听任务。"""
        await self._ready()
        if not self._is_admin(event):
            yield event.plain_result("你没有权限执行这个操作。")
            return
        await self.storage.set_monitor_enabled(task_id, True)
        await self.scheduler.start()
        yield event.plain_result(f"已恢复监听任务：{task_id}")

    @filter.command("bili_monitor_remove")
    async def bili_monitor_remove(self, event: AstrMessageEvent, task_id: str):
        """删除监听任务。"""
        await self._ready()
        if not self._is_admin(event):
            yield event.plain_result("你没有权限执行这个操作。")
            return
        ok = await self.storage.remove_monitor_task(task_id)
        yield event.plain_result("已删除监听任务。" if ok else "没有找到这个监听任务。")

    @filter.command("bili_monitor_run")
    async def bili_monitor_run(self, event: AstrMessageEvent):
        """手动触发所有到期监听任务。"""
        await self._ready()
        if not self._is_admin(event):
            yield event.plain_result("你没有权限执行这个操作。")
            return
        await self.scheduler.run_once()
        yield event.plain_result("已触发一次监听检查。")

    @filter.command("bili_blacklist_add")
    async def bili_blacklist_add(self, event: AstrMessageEvent, mid: str):
        """加入黑名单。"""
        await self._ready()
        if not self._is_admin(event):
            yield event.plain_result("你没有权限执行这个操作。")
            return
        reason = self._tail_after_args(event.message_str, 2)
        await self.storage.add_blacklisted_user(mid, reason)
        yield event.plain_result(f"已加入黑名单：{mid}")

    @filter.command("bili_blacklist_remove")
    async def bili_blacklist_remove(self, event: AstrMessageEvent, mid: str):
        """移出黑名单。"""
        await self._ready()
        if not self._is_admin(event):
            yield event.plain_result("你没有权限执行这个操作。")
            return
        ok = await self.storage.remove_blacklisted_user(mid)
        yield event.plain_result("已移出黑名单。" if ok else "黑名单中没有这个用户。")

    @filter.command("bili_blacklist_list")
    async def bili_blacklist_list(self, event: AstrMessageEvent):
        """查看黑名单。"""
        await self._ready()
        if not self._is_admin(event):
            yield event.plain_result("你没有权限执行这个操作。")
            return
        rows = await self.storage.list_blacklisted_users()
        if not rows:
            yield event.plain_result("黑名单为空。")
            return
        lines = ["黑名单用户："]
        for mid, reason, created_at in rows:
            lines.append(f"{mid} | {created_at} | {reason or '-'}")
        yield event.plain_result("\n".join(lines))

    @filter.command("bili_like")
    async def bili_like(self, event: AstrMessageEvent, oid: int, rpid: int, action: int = 1):
        """点赞或取消点赞评论。"""
        await self._ready()
        if not self._is_admin(event):
            yield event.plain_result("你没有权限执行这个操作。")
            return
        if self.dry_run:
            yield event.plain_result(f"当前是演练模式，不会实际操作。将设置点赞 action={action}。")
            return
        try:
            await self.client.like_reply(oid=oid, type_=1, rpid=rpid, action=action)
        except Exception as exc:
            yield event.plain_result(self._friendly_error(exc))
            return
        yield event.plain_result("点赞操作已完成。")

    @filter.command("bili_delete")
    async def bili_delete(self, event: AstrMessageEvent, oid: int, rpid: int):
        """删除自己发布的评论，需要确认。"""
        await self._ready()
        if not self._is_admin(event):
            yield event.plain_result("你没有权限执行这个操作。")
            return
        if self.dry_run:
            yield event.plain_result(f"当前是演练模式，不会实际删除。目标 oid={oid}, rpid={rpid}")
            return
        if self.require_confirmation:
            code = secrets.token_hex(3)
            self.confirm_codes[code] = {
                "action": "delete_reply",
                "oid": int(oid),
                "rpid": int(rpid),
                "expires_at": int(time.time()) + 300,
                "sender_id": self._sender_id(event),
            }
            yield event.plain_result(f"删除评论需要确认。5分钟内发送 /bili_confirm {code} 继续。")
            return
        yield event.plain_result(await self._delete_reply_confirmed({"oid": oid, "rpid": rpid}))

    @filter.command("bili_logs_export")
    async def bili_logs_export(self, event: AstrMessageEvent, count: int = 200):
        """导出最近日志为 CSV。"""
        await self._ready()
        if not self._is_admin(event):
            yield event.plain_result("你没有权限执行这个操作。")
            return
        logs = await self.storage.list_reply_logs(limit=max(1, min(int(count), 1000)))
        export_dir = self.data_dir / "exports"
        export_dir.mkdir(exist_ok=True)
        path = export_dir / f"reply_logs_{int(time.time())}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["created_at", "success", "draft_id", "oid", "target_rpid", "reply_text", "error_message"])
            for item in logs:
                writer.writerow([
                    item.created_at,
                    int(item.success),
                    item.draft_id or "",
                    item.oid,
                    item.target_rpid,
                    item.reply_text,
                    item.error_message or "",
                ])
        yield event.plain_result(f"已导出日志：{path}")

    @filter.command("bili_dynamic_draft")
    async def bili_dynamic_draft(self, event: AstrMessageEvent):
        """动态发布草稿安全检查占位，不实际发布。"""
        await self._ready()
        if not self._is_admin(event):
            yield event.plain_result("你没有权限执行这个操作。")
            return
        content = self._tail_after_args(event.message_str, 1)
        if not content:
            yield event.plain_result("用法：/bili_dynamic_draft <动态内容>")
            return
        safety = await self.safety.check_reply_text(content, oid=0, target_rpid=0, mid=0)
        flags = ", ".join(safety.flags) if safety.flags else "无"
        yield event.plain_result(
            "\n".join([
                "动态草稿安全检查完成。当前版本不会实际发布动态。",
                f"允许直接发布：{safety.allowed}",
                f"安全标记：{flags}",
                f"内容：{summarize_text(content, 200)}",
            ])
        )

    @filter.command("bili_edit")
    async def bili_edit(self, event: AstrMessageEvent, draft_id: str):
        """修改草稿内容。"""
        await self._ready()
        if not self._is_admin(event):
            yield event.plain_result("你没有权限执行这个操作。")
            return
        new_text = self._tail_after_args(event.message_str, 2)
        if not new_text:
            yield event.plain_result("用法：/bili_edit <draft_id> <新内容>")
            return
        safety = await self.safety.check_reply_text(new_text, oid=0, target_rpid=0, mid=0)
        if not safety.allowed:
            yield event.plain_result(f"安全检查未通过：{safety.reason}")
            return
        await self.storage.update_draft_text(draft_id, new_text, safety.flags)
        yield event.plain_result(f"草稿已更新：{new_text}")

    @filter.command("bili_reject")
    async def bili_reject(self, event: AstrMessageEvent, draft_id: str):
        """拒绝草稿。"""
        await self._ready()
        if not self._is_admin(event):
            yield event.plain_result("你没有权限执行这个操作。")
            return
        await self.storage.update_draft_status(draft_id, "rejected")
        yield event.plain_result("草稿已拒绝。")

    @filter.command("bili_pending")
    async def bili_pending(self, event: AstrMessageEvent):
        """列出待审核草稿。"""
        await self._ready()
        if not self._is_admin(event):
            yield event.plain_result("你没有权限执行这个操作。")
            return
        drafts = await self.storage.list_pending_drafts(limit=10)
        if not drafts:
            yield event.plain_result("暂无待审核草稿。")
            return
        lines = ["待审核草稿："]
        for draft in drafts:
            level = "评论回复" if draft.root != draft.target_rpid else "主评论"
            lines.append(
                f"{draft.draft_id} | {level} | rpid={draft.target_rpid} | "
                f"root={draft.root} | parent={draft.parent} | {summarize_text(draft.reply_text, 50)}"
            )
        yield event.plain_result("\n".join(lines))

    @filter.command("bili_logs")
    async def bili_logs(self, event: AstrMessageEvent, count: int = 10):
        """查看最近发布日志。"""
        await self._ready()
        if not self._is_admin(event):
            yield event.plain_result("你没有权限执行这个操作。")
            return
        logs = await self.storage.list_reply_logs(limit=max(1, min(int(count), 20)))
        if not logs:
            yield event.plain_result("暂无日志。")
            return
        lines = ["最近日志："]
        for item in logs:
            ok = "成功" if item.success else "失败"
            lines.append(f"{item.created_at} | {ok} | rpid={item.target_rpid} | {summarize_text(item.reply_text, 40)}")
        yield event.plain_result("\n".join(lines))

    @filter.command("bili_help")
    async def bili_help(self, event: AstrMessageEvent):
        """显示帮助。"""
        yield event.plain_result(self._help_text())

    @filter.command("bilihelp")
    async def bilihelp(self, event: AstrMessageEvent):
        """显示完整命令教程。"""
        yield event.plain_result(self._help_text())

    @filter.on_astrbot_loaded()
    async def on_astrbot_loaded(self):
        await self._ready()

    def _register_web_apis(self) -> None:
        register_web_api = getattr(self.context, "register_web_api", None)
        if not callable(register_web_api):
            return
        routes = [
            (f"/{PLUGIN_NAME}/dashboard/status", self.page_status, ["GET"], "Bilibili dashboard status"),
            (f"/{PLUGIN_NAME}/dashboard/qrcode/create", self.page_qrcode_create, ["POST"], "Create Bilibili QR login"),
            (f"/{PLUGIN_NAME}/dashboard/qrcode/poll", self.page_qrcode_poll, ["POST"], "Poll Bilibili QR login"),
        ]
        for path, handler, methods, description in routes:
            try:
                register_web_api(path, handler, methods, description)
            except Exception as exc:
                logger.warning(f"Failed to register web api {path}: {exc}")

    async def page_status(self):
        await self._ready()
        account = None
        account_error = ""
        if self.cookie:
            try:
                nav = await self.client.get_account_nav()
                data = nav.get("data", nav)
                account = {"uname": data.get("uname", "-"), "mid": data.get("mid", "-")}
            except Exception as exc:
                account_error = self._friendly_error(exc)
        tasks = await self.storage.list_monitor_tasks(include_disabled=True)
        drafts = await self.storage.list_pending_drafts(limit=8)
        logs = await self.storage.list_reply_logs(limit=8)
        return self._json_response(
            {
                "ok": True,
                "version": PLUGIN_VERSION,
                "core_package": CORE_PACKAGE,
                "enabled": self.enabled,
                "cookie_configured": bool(self.cookie),
                "dry_run": self.dry_run,
                "auto_reply_enabled": self.auto_reply_enabled,
                "require_confirmation": self.require_confirmation,
                "today_logs": await self.storage.count_logs_today(),
                "account": account,
                "account_error": account_error,
                "tasks": [
                    {
                        "task_id": task.task_id,
                        "bvid": task.bvid,
                        "title": task.title,
                        "enabled": task.enabled,
                        "mode": task.mode,
                        "interval_seconds": task.interval_seconds,
                        "last_checked_at": task.last_checked_at,
                    }
                    for task in tasks[:20]
                ],
                "drafts": [
                    {
                        "draft_id": draft.draft_id,
                        "target_rpid": draft.target_rpid,
                        "root": draft.root,
                        "parent": draft.parent,
                        "level_label": "评论回复" if draft.root != draft.target_rpid else "主评论",
                        "reply_text": summarize_text(draft.reply_text, 120),
                        "safety_flags": draft.safety_flags,
                    }
                    for draft in drafts
                ],
                "logs": [
                    {
                        "created_at": item.created_at,
                        "success": item.success,
                        "target_rpid": item.target_rpid,
                        "reply_text": summarize_text(item.reply_text, 120),
                        "error_message": item.error_message or "",
                    }
                    for item in logs
                ],
            }
        )

    async def page_qrcode_create(self):
        try:
            result = await self.client.create_qrcode_login()
            result["qr_image"] = self._qr_png_data_url(result["url"])
            result["expires_in"] = 180
            return self._json_response({"ok": True, **result})
        except Exception as exc:
            logger.error(f"Failed to create Bilibili QR code: {exc}")
            return self._json_response({"ok": False, "message": self._friendly_error(exc)})

    async def page_qrcode_poll(self):
        try:
            from quart import request

            body = await request.get_json(silent=True) or {}
            qrcode_key = str(body.get("qrcode_key") or "")
            result = await self.client.poll_qrcode_login(qrcode_key)
            if result.get("status") == "confirmed":
                await self._save_bilibili_cookie(str(result.get("cookie") or ""))
                result = {key: value for key, value in result.items() if key != "cookie"}
            return self._json_response({"ok": True, **result})
        except Exception as exc:
            logger.error(f"Failed to poll Bilibili QR code: {exc}")
            return self._json_response({"ok": False, "message": self._friendly_error(exc)})

    async def _startup(self) -> None:
        await self.storage.init()
        for mid in self.config_blacklisted_user_ids:
            await self.storage.add_blacklisted_user(mid, "configured")
        tasks = await self.storage.list_monitor_tasks(include_disabled=False)
        if tasks:
            await self.scheduler.start()

    async def _ready(self) -> None:
        if self._init_task is None:
            self._init_task = asyncio.create_task(self._startup())
        await self._init_task

    async def _notify(self, text: str, origin: str) -> None:
        if not origin:
            logger.warning(f"Bilibili assistant notification dropped without origin: {text}")
            return
        try:
            await self.context.send_message(origin, MessageChain().message(text))
        except Exception as exc:
            logger.error(f"Failed to send bilibili assistant notification: {exc}")

    async def _send_draft(self, draft: ReplyDraft) -> str:
        if draft.status != "pending":
            return f"草稿状态是 {draft.status}，不能发送。"
        safety = await self.safety.check_reply_text(
            reply_text=draft.reply_text,
            oid=draft.oid,
            target_rpid=draft.target_rpid,
            mid=draft.target_mid,
        )
        if not safety.allowed:
            await self.storage.update_draft_status(draft.draft_id, "failed", safety.flags)
            await self.storage.write_reply_log(
                draft_id=draft.draft_id,
                oid=draft.oid,
                target_rpid=draft.target_rpid,
                reply_text=draft.reply_text,
                success=False,
                error_message=safety.reason,
                target_mid=draft.target_mid,
            )
            return f"安全检查未通过：{safety.reason}"
        if self.dry_run:
            await self.storage.write_reply_log(
                draft_id=draft.draft_id,
                oid=draft.oid,
                target_rpid=draft.target_rpid,
                reply_text=draft.reply_text,
                success=True,
                error_message="dry_run",
                target_mid=draft.target_mid,
            )
            return f"当前是演练模式，不会实际发布。\n将发送：{draft.reply_text}"
        try:
            await self.client.send_reply(
                oid=draft.oid,
                type_=draft.type,
                message=draft.reply_text,
                root=draft.root,
                parent=draft.parent,
            )
            await self.storage.update_draft_status(draft.draft_id, "sent")
            await self.storage.write_reply_log(
                draft_id=draft.draft_id,
                oid=draft.oid,
                target_rpid=draft.target_rpid,
                reply_text=draft.reply_text,
                success=True,
                error_message=None,
                target_mid=draft.target_mid,
            )
        except Exception as exc:
            await self.storage.update_draft_status(draft.draft_id, "failed")
            await self.storage.write_reply_log(
                draft_id=draft.draft_id,
                oid=draft.oid,
                target_rpid=draft.target_rpid,
                reply_text=draft.reply_text,
                success=False,
                error_message=str(exc),
                target_mid=draft.target_mid,
            )
            return self._friendly_error(exc)
        return "已发送草稿并写入日志。"

    async def _delete_reply_confirmed(self, payload: Dict[str, Any]) -> str:
        oid = int(payload["oid"])
        rpid = int(payload["rpid"])
        try:
            await self.client.delete_reply(oid=oid, type_=1, rpid=rpid)
            await self.storage.write_reply_log(
                draft_id=None,
                oid=oid,
                target_rpid=rpid,
                reply_text="[delete_reply]",
                success=True,
                error_message=None,
            )
        except Exception as exc:
            await self.storage.write_reply_log(
                draft_id=None,
                oid=oid,
                target_rpid=rpid,
                reply_text="[delete_reply]",
                success=False,
                error_message=str(exc),
            )
            return self._friendly_error(exc)
        return "评论删除请求已完成。"

    async def _status_text(self, include_account: bool) -> str:
        await self._ready()
        lines = [
            f"插件版本：{PLUGIN_VERSION}",
            f"核心包：{CORE_PACKAGE}",
            f"插件目录：{PLUGIN_DIR}",
            f"插件启用：{self.enabled}",
            f"Cookie 已配置：{bool(self.cookie)}",
            f"dry_run：{self.dry_run}",
            f"auto_reply：{self.auto_reply_enabled}",
            f"require_confirmation：{self.require_confirmation}",
            f"今日日志数：{await self.storage.count_logs_today()}",
        ]
        if include_account and self.cookie:
            try:
                nav = await self.client.get_account_nav()
                data = nav.get("data", nav)
                lines.append(f"B站账号：{data.get('uname', '-')}({data.get('mid', '-')})")
            except Exception as exc:
                lines.append(self._friendly_error(exc))
        return "\n".join(lines)

    def _version_text(self) -> str:
        return "\n".join(
            [
                f"插件版本：{PLUGIN_VERSION}",
                f"插件名称：{PLUGIN_NAME}",
                f"核心包：{CORE_PACKAGE}",
                f"插件目录：{PLUGIN_DIR}",
                "如果这里不是 v0.2.13，说明 AstrBot 仍在加载旧目录或旧 zip。",
            ]
        )

    def _help_text(self) -> str:
        return "\n".join(
            [
                "B站评论助手命令教程",
                "",
                "基础检查",
                "/bilihelp 或 /bili_help",
                "  显示这份完整命令教程。",
                "/bili_version",
                "  查看 AstrBot 实际加载的插件版本、核心包和插件目录。",
                "/bilicomment_status",
                "  快速查看插件开关、Cookie、演练模式、自动回复和今日日志数。",
                "/bili_status",
                "  查看插件状态，并尝试读取 B站账号信息验证 Cookie 是否可用。",
                "",
                "开关和登录",
                "/bilicomment_on",
                "  启用当前运行实例里的插件功能。",
                "/bilicomment_off",
                "  关闭当前运行实例里的插件功能。",
                "/bili_bind",
                "  提示去 WebUI 配置或 Dashboard 扫码登录，不会在聊天里接收 Cookie。",
                "",
                "视频和评论",
                "/bili_video <BV号>",
                "  查询视频标题、aid、bvid、UP 主和评论区参数。",
                "  示例：/bili_video BV1xxxxxxx",
                "/bili_comments <BV号> [数量]",
                "  拉取视频最新评论，数量范围会限制在 1 到 10。",
                "  返回内容会区分【主评论】和【评论回复】，并显示 rpid、root、parent。",
                "  示例：/bili_comments BV1xxxxxxx 5",
                "",
                "草稿审核和发送",
                "/bili_draft <BV号> <rpid> [风格]",
                "  针对某条评论生成回复草稿，建议先用 /bili_comments 获取 rpid。",
                "  风格可用：friendly、official、cute、concise、humorous。",
                "  示例：/bili_draft BV1xxxxxxx 123456 friendly",
                "/bili_ai_rpid <BV号> <rpid> [风格]",
                "  根据评论 rpid 调用 AI 生成回复，只展示文本，不保存草稿也不发布。",
                "  示例：/bili_ai_rpid BV1xxxxxxx 123456 cute",
                "/bili_ai_reply [风格] <需要回复的内容>",
                "  不依赖 B站评论 ID，直接根据输入内容用 AI 生成一条回复草稿。",
                "  示例：/bili_ai_reply cute 太好看了，期待下一期",
                "/bili_ai_check",
                "  测试插件能否调用 AstrBot 当前会话模型；如果失败会退回固定模板。",
                "/bili_pending",
                "  查看待审核草稿。",
                "/bili_edit <draft_id> <新内容>",
                "  修改草稿内容。注意命令后面的所有文本都会作为新回复。",
                "/bili_reject <draft_id>",
                "  拒绝并关闭某条草稿。",
                "/bili_send <draft_id>",
                "  发送草稿；dry_run 开启时只演练，不会真实发到 B站。",
                "/bili_confirm <确认码>",
                "  require_confirmation 开启时，用确认码完成真实发送或删除。",
                "/bili_dryrun on",
                "  开启演练模式，所有发送、点赞、删除都不会真实执行。",
                "/bili_dryrun off",
                "  关闭演练模式，后续操作可能真实请求 B站。",
                "",
                "监听任务",
                "/bili_monitor_add <BV号> [notify_only|draft|auto_reply] [间隔秒]",
                "  添加评论监听任务。",
                "  notify_only 只通知；draft 生成草稿；auto_reply 尝试自动回复。",
                "  示例：/bili_monitor_add BV1xxxxxxx draft 300",
                "/bili_monitor_list",
                "  查看所有监听任务。",
                "/bili_monitor_pause <task_id>",
                "  暂停监听任务。",
                "/bili_monitor_resume <task_id>",
                "  恢复监听任务。",
                "/bili_monitor_remove <task_id>",
                "  删除监听任务。",
                "/bili_monitor_run",
                "  手动触发一次所有到期监听任务。",
                "",
                "黑名单和评论操作",
                "/bili_blacklist_add <mid>",
                "  将 B站用户 mid 加入黑名单。",
                "/bili_blacklist_remove <mid>",
                "  将 B站用户 mid 移出黑名单。",
                "/bili_blacklist_list",
                "  查看黑名单。",
                "/bili_like <oid> <rpid> [1|0]",
                "  点赞或取消点赞评论。1 表示点赞，0 表示取消。",
                "/bili_delete <oid> <rpid>",
                "  删除自己发布的评论，通常需要确认码。",
                "",
                "日志和其他",
                "/bili_logs [数量]",
                "  查看最近发布日志，默认 10 条。",
                "/bili_logs_export [数量]",
                "  导出最近日志为 CSV，默认 200 条。",
                "/bili_dynamic_draft",
                "  动态发布草稿安全检查占位命令，目前不会真实发布动态。",
                "",
                "推荐流程",
                "1. /bili_version 确认版本",
                "2. Dashboard 扫码登录或配置 Cookie",
                "3. /bili_status 验证账号",
                "4. /bili_comments BV1xxxxxxx 5 获取 rpid",
                "5. /bili_ai_rpid BV1xxxxxxx <rpid> friendly 先试写",
                "6. /bili_draft BV1xxxxxxx <rpid> friendly 保存草稿",
                "7. /bili_pending 查看草稿",
                "8. /bili_send <draft_id> 演练或发送",
                "也可以用 /bili_ai_reply <内容> 先让 AI 试写一条回复。",
                "",
                "安全提示",
                "首次建议保持 dry_run=true 和 require_confirmation=true。",
                "Cookie 是账号凭证，不要发到群聊或提交到仓库。",
                "B站可能风控服务器请求，遇到风控请降低频率、扫码登录或更换出口网络。",
            ]
        )

    async def _get_replies(
        self,
        *,
        oid: int,
        type_: int = 1,
        page: int = 1,
        sort: int = 1,
        bvid: str = "",
    ):
        try:
            return await self.client.get_replies(
                oid=oid,
                type_=type_,
                page=page,
                sort=sort,
                bvid=bvid,
            )
        except TypeError as exc:
            if "unexpected keyword argument 'bvid'" not in str(exc):
                raise
            logger.warning("Loaded BilibiliClient does not support bvid yet; retrying without it.")
            return await self.client.get_replies(oid=oid, type_=type_, page=page, sort=sort)

    async def _find_comment(self, aid: int, rpid: int, bvid: str = "") -> Optional[Comment]:
        stored = await self.storage.get_seen_comment(rpid)
        if stored:
            return stored
        comments = await self._get_replies(oid=aid, type_=1, page=1, sort=1, bvid=bvid)
        for comment in comments:
            await self.storage.save_seen_comment(comment)
            if comment.rpid == rpid:
                return comment
        return None

    def _is_admin(self, event: AstrMessageEvent) -> bool:
        if not self.admin_user_ids:
            return True
        sender_id = self._sender_id(event)
        return sender_id in self.admin_user_ids

    def _sender_id(self, event: AstrMessageEvent) -> str:
        try:
            return str(event.get_sender_id())
        except Exception:
            message_obj = getattr(event, "message_obj", None)
            sender = getattr(message_obj, "sender", None)
            return str(getattr(sender, "user_id", "") or getattr(sender, "id", ""))

    def _origin(self, event: AstrMessageEvent) -> str:
        return str(getattr(event, "unified_msg_origin", "") or "")

    def _data_dir(self) -> Path:
        path = Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def _save_bilibili_cookie(self, cookie: str) -> None:
        parsed = BilibiliClient(cookie=cookie)
        if parsed.cookie_error:
            await parsed.aclose()
            raise parsed.cookie_error
        old_client = self.client
        self.cookie = cookie
        self.config["bilibili_cookie"] = cookie
        save_config = getattr(self.config, "save_config", None)
        if callable(save_config):
            result = save_config()
            if inspect.isawaitable(result):
                await result
        self.client = parsed
        self.scheduler.client = parsed
        await old_client.aclose()

    def _qr_png_data_url(self, url: str) -> str:
        try:
            import qrcode

            qr = qrcode.QRCode(
                version=None,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=1,
                border=4,
            )
            qr.add_data(url)
            qr.make(fit=True)
            matrix = qr.get_matrix()
            png_bytes = self._matrix_to_png(matrix, scale=6)
            encoded = base64.b64encode(png_bytes).decode("ascii")
            return f"data:image/png;base64,{encoded}"
        except Exception as exc:
            logger.warning(f"Failed to generate QR PNG: {exc}")
            return ""

    def _matrix_to_png(self, matrix, scale: int = 6) -> bytes:
        size = len(matrix)
        width = size * scale
        height = size * scale
        rows = []
        for row in matrix:
            line = bytearray()
            for dark in row:
                line.extend([0 if dark else 255] * scale)
            scanline = bytes([0]) + bytes(line)
            rows.extend([scanline] * scale)
        raw = b"".join(rows)

        def chunk(kind: bytes, data: bytes) -> bytes:
            return (
                struct.pack(">I", len(data))
                + kind
                + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
            )

        header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b"")
        )

    def _json_response(self, payload: Dict[str, Any], status: int = 200):
        try:
            from quart import jsonify

            response = jsonify(payload)
            response.status_code = status
            return response
        except Exception:
            return payload

    def _tail_after_args(self, message_str: str, token_count: int) -> str:
        parts = (message_str or "").strip().split(maxsplit=token_count)
        if len(parts) <= token_count:
            return ""
        return parts[token_count].strip()

    def _split_style_and_content(self, raw: str) -> tuple[str, str]:
        raw = (raw or "").strip()
        if not raw:
            return self.reply_style, ""
        styles = {"friendly", "official", "cute", "concise", "humorous"}
        parts = raw.split(maxsplit=1)
        if parts and parts[0] in styles:
            return parts[0], parts[1].strip() if len(parts) > 1 else ""
        return self.reply_style, raw

    def _generation_note(self) -> str:
        source = getattr(self.generator, "last_source", "")
        provider_id = getattr(self.generator, "last_provider_id", "") or "-"
        if source == "ai":
            return f"生成来源：AI（provider_id={provider_id}）"
        if source == "template":
            error = getattr(self.generator, "last_error", "") or "未知错误"
            return f"生成来源：固定模板兜底（AI调用失败：{summarize_text(error, 120)}）"
        return "生成来源：未知"

    async def _current_chat_provider_id(self, event: AstrMessageEvent) -> Optional[str]:
        if self.generator.chat_provider_id:
            return self.generator.chat_provider_id
        getter = getattr(self.context, "get_current_chat_provider_id", None)
        if not callable(getter):
            return None
        try:
            return await getter(umo=getattr(event, "unified_msg_origin", ""))
        except TypeError:
            try:
                return await getter(getattr(event, "unified_msg_origin", ""))
            except Exception:
                return None
        except Exception:
            return None

    def _friendly_error(self, exc: Exception) -> str:
        if isinstance(exc, BiliApiError):
            return exc.user_message
        text = str(exc)
        if "bili_jct" in text:
            return "Cookie 中没有找到 bili_jct，无法发布评论。"
        if "cookie" in text.lower():
            return "还没有配置 B站 Cookie，请先在插件配置中填写。"
        return f"操作失败：{text}"

    async def terminate(self):
        if self._init_task is not None:
            try:
                await self._init_task
            except Exception as exc:
                logger.warning(f"Bilibili assistant startup did not finish cleanly: {exc}")
        await self.scheduler.stop()
        await self.client.aclose()
