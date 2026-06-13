from __future__ import annotations

import asyncio
from http.cookies import SimpleCookie
from typing import Any, Dict, List, Optional

import httpx

from .models import Comment
from .utils import parse_cookie_string


API_NAV = "https://api.bilibili.com/x/web-interface/nav"
API_VIDEO_INFO = "https://api.bilibili.com/x/web-interface/view"
API_REPLY_MAIN = "https://api.bilibili.com/x/v2/reply/main"
API_REPLY_LEGACY = "https://api.bilibili.com/x/v2/reply"
API_REPLY_ADD = "https://api.bilibili.com/x/v2/reply/add"
API_REPLY_ACTION = "https://api.bilibili.com/x/v2/reply/action"
API_REPLY_DEL = "https://api.bilibili.com/x/v2/reply/del"
API_QRCODE_GENERATE = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
API_QRCODE_POLL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"


class BiliApiError(RuntimeError):
    def __init__(self, user_message: str, *, code: Optional[int] = None, detail: str = ""):
        self.user_message = user_message
        self.code = code
        self.detail = detail
        super().__init__(detail or user_message)


class BilibiliClient:
    def __init__(self, cookie: str, timeout: int = 10):
        self.cookie = cookie.strip()
        self.timeout = timeout
        self.cookie_error: Optional[BiliApiError] = None
        try:
            self.cookies = self.parse_cookie(cookie) if cookie.strip() else {}
        except BiliApiError as exc:
            self.cookie_error = exc
            self.cookies = {}
        self.csrf = self.cookies.get("bili_jct", "")
        self.headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.bilibili.com/",
            "Origin": "https://www.bilibili.com",
        }
        session_headers = dict(self.headers)
        if self.cookie:
            session_headers["Cookie"] = self.cookie
        self.session = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            headers=session_headers,
            follow_redirects=True,
        )

    def parse_cookie(self, cookie: str) -> Dict[str, str]:
        data = parse_cookie_string(cookie)
        if not data.get("SESSDATA"):
            raise BiliApiError("Cookie 中缺少 SESSDATA，请重新获取登录 Cookie。")
        if not data.get("bili_jct"):
            raise BiliApiError("Cookie 中没有找到 bili_jct，无法发布评论。")
        return data

    async def aclose(self) -> None:
        await self.session.aclose()

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        auth_required: bool = False,
        retries: int = 2,
    ) -> Dict[str, Any]:
        if auth_required and not self.cookie:
            raise BiliApiError("还没有配置 B站 Cookie，请先在插件配置中填写。")
        last_error: Optional[Exception] = None
        for attempt in range(retries + 1):
            try:
                resp = await self.session.request(method, url, params=params, data=data, headers=headers)
                if resp.status_code >= 400:
                    raise BiliApiError(
                        self._status_to_message(resp.status_code),
                        detail=resp.text[:300],
                    )
                payload = resp.json()
                code = int(payload.get("code", 0))
                if code != 0:
                    raise BiliApiError(
                        self._code_to_message(code, str(payload.get("message", ""))),
                        code=code,
                        detail=str(payload),
                    )
                return payload
            except (httpx.TimeoutException, httpx.NetworkError, ValueError, BiliApiError) as exc:
                last_error = exc
                if isinstance(exc, BiliApiError):
                    raise
                if attempt >= retries:
                    break
                await asyncio.sleep(0.5 * (2**attempt))
        raise BiliApiError("请求 B站失败，请稍后再试。", detail=str(last_error))

    async def get_account_nav(self) -> Dict[str, Any]:
        if self.cookie_error:
            raise self.cookie_error
        return await self._request("GET", API_NAV, auth_required=True)

    async def get_replies(
        self,
        oid: int,
        type_: int = 1,
        page: int = 1,
        sort: int = 1,
        bvid: str = "",
    ) -> List[Comment]:
        errors: List[str] = []
        referer = f"https://www.bilibili.com/video/{bvid}/" if bvid else None
        for getter in (
            self._get_replies_legacy,
            self._get_replies_legacy_no_sort,
            self._get_replies_main,
            self._get_replies_main_alt,
        ):
            try:
                return await getter(oid=oid, type_=type_, page=page, sort=sort, referer=referer)
            except BiliApiError as exc:
                if exc.code not in {-400, -404, 12002, 12009}:
                    raise
                errors.append(self._error_summary(exc))
        raise BiliApiError(
            "读取评论失败，B站评论接口参数可能已调整："
            + "；".join(errors[-2:] or ["没有可用的错误详情"]),
            detail=" | ".join(errors),
        )

    async def _get_replies_main(
        self,
        oid: int,
        type_: int,
        page: int,
        sort: int,
        referer: Optional[str] = None,
    ) -> List[Comment]:
        mode = 2 if int(sort) == 2 else 3
        payload = await self._request(
            "GET",
            API_REPLY_MAIN,
            params={
                "oid": oid,
                "type": type_,
                "next": max(page, 1),
                "mode": mode,
                "ps": 20,
                "plat": 1,
                "web_location": "1315875",
            },
            headers=self._browser_headers(referer),
        )
        replies = payload.get("data", {}).get("replies") or []
        return self._comments_from_items(replies, oid=oid, type_=type_)

    async def _get_replies_legacy(
        self,
        oid: int,
        type_: int,
        page: int,
        sort: int,
        referer: Optional[str] = None,
    ) -> List[Comment]:
        legacy_sort = 2 if int(sort) != 0 else 0
        payload = await self._request(
            "GET",
            API_REPLY_LEGACY,
            params={
                "jsonp": "jsonp",
                "oid": oid,
                "type": type_,
                "pn": max(page, 1),
                "ps": 20,
                "sort": legacy_sort,
            },
            headers=self._browser_headers(referer),
        )
        replies = payload.get("data", {}).get("replies") or []
        return self._comments_from_items(replies, oid=oid, type_=type_)

    async def _get_replies_legacy_no_sort(
        self,
        oid: int,
        type_: int,
        page: int,
        sort: int,
        referer: Optional[str] = None,
    ) -> List[Comment]:
        payload = await self._request(
            "GET",
            API_REPLY_LEGACY,
            params={
                "jsonp": "jsonp",
                "oid": oid,
                "type": type_,
                "pn": max(page, 1),
                "ps": 20,
            },
            headers=self._browser_headers(referer),
        )
        replies = payload.get("data", {}).get("replies") or []
        return self._comments_from_items(replies, oid=oid, type_=type_)

    async def _get_replies_main_alt(
        self,
        oid: int,
        type_: int,
        page: int,
        sort: int,
        referer: Optional[str] = None,
    ) -> List[Comment]:
        payload = await self._request(
            "GET",
            API_REPLY_MAIN,
            params={
                "oid": oid,
                "type": type_,
                "next": max(page - 1, 0),
                "mode": 2,
                "ps": 20,
                "plat": 1,
                "web_location": "1315875",
            },
            headers=self._browser_headers(referer),
        )
        replies = payload.get("data", {}).get("replies") or []
        return self._comments_from_items(replies, oid=oid, type_=type_)

    def _browser_headers(self, referer: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "Referer": referer or "https://www.bilibili.com/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
        }
        if self.cookie:
            headers["Cookie"] = self.cookie
        return headers

    def _comments_from_items(self, replies: List[Dict[str, Any]], oid: int, type_: int) -> List[Comment]:
        comments: List[Comment] = []
        for item in replies:
            root_comment = Comment.from_bili(item, oid=oid, type_=type_)
            comments.append(root_comment)
            for child in item.get("replies") or []:
                child_comment = Comment.from_bili(child, oid=oid, type_=type_)
                if child_comment.root == 0:
                    child_comment.root = root_comment.rpid
                if child_comment.parent == 0:
                    child_comment.parent = root_comment.rpid
                comments.append(child_comment)
        return comments

    async def send_reply(
        self,
        oid: int,
        type_: int,
        message: str,
        root: int = 0,
        parent: int = 0,
    ) -> Dict[str, Any]:
        if not self.csrf:
            if self.cookie_error:
                raise self.cookie_error
            raise BiliApiError("Cookie 中没有找到 bili_jct，无法发布评论。")
        data: Dict[str, Any] = {
            "oid": oid,
            "type": type_,
            "message": message,
            "plat": 1,
            "csrf": self.csrf,
        }
        if root:
            data["root"] = root
        if parent:
            data["parent"] = parent
        return await self._request("POST", API_REPLY_ADD, data=data, auth_required=True)

    async def like_reply(self, oid: int, type_: int, rpid: int, action: int = 1) -> Dict[str, Any]:
        if not self.csrf:
            if self.cookie_error:
                raise self.cookie_error
            raise BiliApiError("Cookie 中没有找到 bili_jct，无法点赞评论。")
        return await self._request(
            "POST",
            API_REPLY_ACTION,
            data={"oid": oid, "type": type_, "rpid": rpid, "action": action, "csrf": self.csrf},
            auth_required=True,
        )

    async def delete_reply(self, oid: int, type_: int, rpid: int) -> Dict[str, Any]:
        if not self.csrf:
            if self.cookie_error:
                raise self.cookie_error
            raise BiliApiError("Cookie 中没有找到 bili_jct，无法删除评论。")
        return await self._request(
            "POST",
            API_REPLY_DEL,
            data={"oid": oid, "type": type_, "rpid": rpid, "csrf": self.csrf},
            auth_required=True,
        )

    async def get_video_info_by_bvid(self, bvid: str) -> Dict[str, Any]:
        payload = await self._request("GET", API_VIDEO_INFO, params={"bvid": bvid})
        return payload.get("data") or {}

    async def create_qrcode_login(self) -> Dict[str, str]:
        payload = await self._request("GET", API_QRCODE_GENERATE)
        data = payload.get("data") or {}
        url = str(data.get("url") or "")
        qrcode_key = str(data.get("qrcode_key") or "")
        if not url or not qrcode_key:
            raise BiliApiError("B站扫码登录二维码生成失败，请稍后再试。", detail=str(payload))
        return {"url": url, "qrcode_key": qrcode_key}

    async def poll_qrcode_login(self, qrcode_key: str) -> Dict[str, Any]:
        if not qrcode_key:
            raise BiliApiError("缺少二维码 key，请重新生成二维码。")
        try:
            resp = await self.session.get(API_QRCODE_POLL, params={"qrcode_key": qrcode_key})
            if resp.status_code >= 400:
                raise BiliApiError(
                    self._status_to_message(resp.status_code),
                    detail=resp.text[:300],
                )
            payload = resp.json()
        except (httpx.TimeoutException, httpx.NetworkError, ValueError) as exc:
            raise BiliApiError("轮询扫码状态失败，请稍后再试。", detail=str(exc)) from exc

        if int(payload.get("code", 0)) != 0:
            raise BiliApiError(
                self._code_to_message(int(payload.get("code", 0)), str(payload.get("message", ""))),
                detail=str(payload),
            )
        data = payload.get("data") or {}
        status_code = int(data.get("code", -1))
        if status_code == 0:
            cookie = self.cookie_header_from_response(resp)
            if not cookie:
                raise BiliApiError("扫码成功但没有拿到 Cookie，请重新扫码或手动填写。", detail=str(payload))
            return {"status": "confirmed", "message": "扫码登录成功。", "cookie": cookie}
        if status_code == 86101:
            return {"status": "waiting", "message": "等待扫码。"}
        if status_code == 86090:
            return {"status": "scanned", "message": "已扫码，请在 B站客户端确认登录。"}
        if status_code == 86038:
            return {"status": "expired", "message": "二维码已过期，请重新生成。"}
        return {
            "status": "unknown",
            "message": str(data.get("message") or f"B站返回扫码状态 {status_code}。"),
        }

    @staticmethod
    def cookie_header_from_response(resp: httpx.Response) -> str:
        preferred = [
            "SESSDATA",
            "bili_jct",
            "DedeUserID",
            "DedeUserID__ckMd5",
            "sid",
            "buvid3",
            "buvid4",
            "b_nut",
        ]
        cookies: Dict[str, str] = {}
        for header in resp.headers.get_list("set-cookie"):
            parsed = SimpleCookie()
            parsed.load(header)
            for name, morsel in parsed.items():
                cookies[name] = morsel.value
        if not cookies:
            try:
                for item in resp.cookies.jar:
                    cookies[item.name] = item.value
            except RuntimeError:
                pass
        return "; ".join(f"{name}={cookies[name]}" for name in preferred if cookies.get(name))

    def _status_to_message(self, status_code: int) -> str:
        if status_code in {401, 403}:
            return "B站登录状态可能失效了，请重新获取 Cookie。"
        if status_code == 412:
            return "请求被B站风控拦截了。建议先在 Dashboard 扫码配置 Cookie，降低请求频率；如果部署在服务器或容器里，可能需要更换出口网络后再试。"
        return f"B站接口返回 HTTP {status_code}。"

    def _error_summary(self, exc: BiliApiError) -> str:
        detail = exc.detail or exc.user_message
        if len(detail) > 180:
            detail = detail[:177] + "..."
        return f"code={exc.code}, {detail}"

    def _code_to_message(self, code: int, message: str) -> str:
        if code in {-101, -102}:
            return "B站登录状态可能失效了，请重新获取 Cookie。"
        if code in {-111, -400}:
            if "min_score" in message or "max_score" in message:
                return "B站评论接口参数已变化，正在尝试兼容旧接口；如果仍失败请稍后再试。"
            return f"B站接口参数错误：{message or code}"
        if code in {-404, 12002}:
            return "这个视频或评论区可能不存在。"
        if code in {12022, 12051}:
            return "这个视频的评论区可能关闭了。"
        if code in {-352, -412}:
            return "请求被B站风控拦截了。建议先在 Dashboard 扫码配置 Cookie，降低请求频率；如果部署在服务器或容器里，可能需要更换出口网络后再试。"
        return message or f"B站接口返回错误 code={code}。"
