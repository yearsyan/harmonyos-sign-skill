"""harmonyos-sign CLI - HarmonyOS 签名工具包

用法:
  python3 -m harmonyos_sign check-env
  python3 -m harmonyos_sign fetch-udid
  python3 -m harmonyos_sign oauth-login [--timeout 300]  # 生成授权URL等待回调，浏览器操作由agent完成
  python3 -m harmonyos_sign online-sign <unsigned.hap> <bundleName> <certId> <deviceId> [--cert cert.cer] [--p12 key.p12]
  python3 -m harmonyos_sign certs | devices
  python3 -m harmonyos_sign verify <signed.hap>
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .core import (hdc, find_hdc, find_ohpm, find_hvigorw,
                   describe_toolchain, verify_app)
from .oauth import oauth_login
from .online import online_sign, query_certs, query_devices


def cmd_check_env(_: argparse.Namespace) -> int:
    ok = fail = 0
    def chk(name, cond, hint=""):
        nonlocal ok, fail
        if cond:
            print(f"  [✓] {name}"); ok += 1
        else:
            print(f"  [✗] {name} {hint}"); fail += 1
    print("== 工具链自动发现 ==")
    print(describe_toolchain())
    print()
    h = find_hdc()
    chk("hdc", h is not None, "(设置 HOS 或 DEVECO_SDK_HOME，或安装工具链)")
    chk("hap-sign-tool.jar", h is not None and (h.parent / "lib/hap-sign-tool.jar").exists())
    chk("ohpm", find_ohpm() is not None)
    chk("hvigorw", find_hvigorw() is not None)
    chk("udev 规则", Path("/etc/udev/rules.d/51-harmonyos.rules").exists(), "(hdc 连接真机需要)")
    print(f"\n结果: {ok} 通过, {fail} 失败")
    return 1 if fail else 0


def cmd_fetch_udid(_: argparse.Namespace) -> int:
    r = subprocess.run([str(hdc()), "list", "targets"], capture_output=True, text=True, timeout=30)
    print(r.stdout.strip())
    for t in r.stdout.split():
        if t in ("[Empty]", ""):
            continue
        u = subprocess.run([str(hdc()), "-t", t, "shell", "bm", "get", "-u"],
                           capture_output=True, text=True, timeout=30)
        print(f"--- {t} ---\n{u.stdout.strip()}")
    return 0


def cmd_oauth(a: argparse.Namespace) -> int:
    oauth_login(port=a.port, timeout=a.timeout)
    return 0


def cmd_online(a: argparse.Namespace) -> int:
    out = online_sign(a.hap, a.bundle, a.cert_id, a.device_id, a.cert, a.p12, a.alias)
    print(f"✅ 安装完成: {out}")
    return 0


def cmd_verify(a: argparse.Namespace) -> int:
    return 0 if verify_app(a.hap) else 1


def cmd_certs(a: argparse.Namespace) -> int:
    from .core import oauth_dir
    token = (oauth_dir() / "oauth2token.txt").read_text().strip()
    uid = (oauth_dir() / "uid.txt").read_text().strip()
    for c in query_certs(token, uid):
        print(f"{c['id']}  {c['certName']}  {c.get('sha256','')[:16]}  expire={c.get('expireTime')}")
    return 0


def cmd_devices(a: argparse.Namespace) -> int:
    from .core import oauth_dir
    token = (oauth_dir() / "oauth2token.txt").read_text().strip()
    uid = (oauth_dir() / "uid.txt").read_text().strip()
    for d in query_devices(token, uid):
        print(f"{d['id']}  {d['deviceName']}  {d['udid'][:16]}...  type={d['deviceType']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="harmonyos-sign", description="HarmonyOS 签名工具包")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check-env", help="检查环境").set_defaults(fn=cmd_check_env)
    sub.add_parser("fetch-udid", help="读取已连接设备 UDID").set_defaults(fn=cmd_fetch_udid)
    v = sub.add_parser("verify", help="验证 HAP 签名")
    v.add_argument("hap")
    v.set_defaults(fn=cmd_verify)

    o = sub.add_parser("oauth-login", help="生成授权 URL 并等待回调，兑换 oauth2Token")
    o.add_argument("--timeout", type=int, default=300, help="等待回调超时秒数（默认 300=5min）")
    o.add_argument("--port", type=int, default=18487, help="本地回调端口")
    o.set_defaults(fn=cmd_oauth)

    o = sub.add_parser("online-sign", help="在线签名 + 安装（HarmonyOS）")
    o.add_argument("hap"); o.add_argument("bundle")
    o.add_argument("cert_id"); o.add_argument("device_id")
    o.add_argument("--cert", help="云证书链 .cer"); o.add_argument("--p12", help="本地私钥库")
    o.add_argument("--alias", default="online-app"); o.set_defaults(fn=cmd_online)

    sub.add_parser("certs", help="列出云端证书").set_defaults(fn=cmd_certs)
    sub.add_parser("devices", help="列出云端设备").set_defaults(fn=cmd_devices)

    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except KeyboardInterrupt:
        return 130
    except Exception as e:  # noqa: BLE001
        print(f"错误: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
