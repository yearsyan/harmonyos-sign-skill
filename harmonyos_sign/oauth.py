"""DevEco 客户端 OAuth 登录模拟：生成授权 URL -> 等待回调 -> 兑换 oauth2Token

职责边界（简洁版）：
  * 本脚本只做三件事：生成授权 URL、启动本地回调服务器、token 兑换
  * 浏览器操作（打开 URL、登录、点击「允许」）由 **agent 自主选择工具**完成：
    Kimi WebBridge / Chrome DevTools MCP / Playwright CLI / 其他
  * 回调到达后自动继续；默认等待 5 分钟，超时则停止并提示用户

用法:
  python3 -m harmonyos_sign oauth-login [--timeout 300] [--port 18487]
  输出授权 URL 后，由 agent 用其浏览器工具打开该 URL 完成授权。
"""
from __future__ import annotations

import argparse
import http.server
import json
import socket
import threading
import time
import urllib.parse
import urllib.request
import uuid

from .core import oauth_dir

BASE = "https://cn.devecostudio.huawei.com"
APPID = 1007
VERSION = "6.1.1.300"
UA = {"User-Agent": "Chrome/49.0.2623.75", "Accept": "*/*", "Accept-Encoding": "identity"}

_callback: dict = {}


# ---------------------------------------------------------------- 回调服务器
class _V6HTTPServer(http.server.HTTPServer):
    address_family = socket.AF_INET6
    allow_reuse_address = True


class _CBHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _handle(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode(errors="replace") if length else ""
        _callback["raw"] = f"{self.command} {self.path}\n{body}"
        parts = urllib.parse.parse_qs(body)
        tk = parts.get("tempToken", [""])[0]
        # 仅 POST 回调且含 tempToken 时记录（favicon 等 GET 不得覆盖）
        if self.command == "POST" and tk and not _callback.get("tempToken"):
            _callback["tempToken"] = tk
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    do_GET = _handle
    do_POST = _handle


def _start_cb_server(port: int) -> list[http.server.HTTPServer]:
    """双监听 127.0.0.1 与 ::1（兼容 localhost 解析差异）"""
    servers = []
    for host, cls in (("127.0.0.1", http.server.HTTPServer), ("::1", _V6HTTPServer)):
        try:
            srv = cls((host, port), _CBHandler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            servers.append(srv)
        except OSError:
            pass
    if not servers:
        raise RuntimeError(f"回调服务器启动失败（端口 {port} 被占用？）")
    return servers


# ---------------------------------------------------------------- 主流程
def generate_auth_url(port: int = 18487) -> str:
    """生成授权 URL（appid=1007 + 本地回调端口 + 一次性 code）"""
    code = uuid.uuid4().hex
    return f"{BASE}/console/DevEcoIDE/apply?port={port}&appid={APPID}&code={code}"


def oauth_login(port: int = 18487, timeout: int = 300) -> str:
    """等待授权回调并兑换 oauth2Token。

    流程：打印授权 URL -> 等待浏览器回调（agent/用户操作）-> tempToken ->
          jwtToken -> oauth2Token。超时则抛错并提示。
    """
    servers = _start_cb_server(port)
    url = generate_auth_url(port)
    print("=" * 64)
    print("请完成华为账号授权（由 agent 或用户打开以下 URL）：")
    print(f"  {url}")
    print(f"  打开后：已登录则点击「允许」；未登录则先登录再允许。")
    print(f"  回调端口 {port} 已就绪，等待授权回调（最多 {timeout}s）...")
    print("=" * 64)

    deadline = time.time() + timeout
    while time.time() < deadline:
        if _callback.get("tempToken"):
            break
        time.sleep(1)
    temp = _callback.get("tempToken", "")
    if not temp:
        for s in servers:
            s.shutdown()
        raise RuntimeError(
            f"授权超时（{timeout}s 内未收到回调）。请检查："
            f"① 浏览器是否打开了授权 URL 并点击「允许」"
            f"② 回调端口 {port} 是否被占用"
            f"③ 可重试 oauth-login 生成新 URL")

    # tempToken -> jwtToken
    q = urllib.parse.urlencode({"tempToken": temp, "site": "CN",
                                "version": VERSION, "appid": APPID})
    jwt = _http_get(f"{BASE}/authrouter/auth/api/temptoken/check?{q}")
    if len(jwt) < 100:
        for s in servers:
            s.shutdown()
        raise RuntimeError(f"jwtToken 获取失败: {jwt[:200]}")
    print(f"== jwtToken 获取成功 (长度 {len(jwt)})")

    # jwtToken -> accessToken
    resp = _http_get(f"{BASE}/authrouter/auth/api/jwToken/check",
                     extra={"jwtToken": jwt, "refresh": "false"})
    data = json.loads(resp)
    ui = data.get("userInfo", {})
    at = ui.get("accessToken", "")
    if not at:
        for s in servers:
            s.shutdown()
        raise RuntimeError(f"accessToken 获取失败: {resp[:300]}")
    out = oauth_dir()
    (out / "oauth2token.txt").write_text(at)
    (out / "jwt.txt").write_text(jwt)
    (out / "uid.txt").write_text(ui.get("userId", ""))
    print(f"✅ oauth2Token 已保存 -> {out / 'oauth2token.txt'} (长度 {len(at)})")
    print(f"   userId: {ui.get('userId')} | realName: {ui.get('realName')}")
    for s in servers:
        s.shutdown()
    return at


def _http_get(url: str, extra: dict | None = None) -> str:
    req = urllib.request.Request(url, headers={**UA, **(extra or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode()
