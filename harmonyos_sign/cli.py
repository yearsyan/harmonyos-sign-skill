"""harmonyos-sign CLI - HarmonyOS 签名工具包

用法:
  python3 -m harmonyos_sign check-env
  python3 -m harmonyos_sign fetch-udid
  python3 -m harmonyos_sign oauth-login [--timeout 300]  # 生成授权URL等待回调，浏览器操作由agent完成
  python3 -m harmonyos_sign new-cert                      # 生成p12+CSR→云端签发证书→下载.cer（幂等，已有则复用）
  python3 -m harmonyos_sign online-sign <unsigned.hap> <bundleName> [certId] [deviceId]
                                                          # certId/deviceId 可省略：自动签发/匹配/注册
  python3 -m harmonyos_sign certs | devices
  python3 -m harmonyos_sign verify <signed.hap>
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .core import (hdc, describe_toolchain, verify_app, oauth_dir)
from .oauth import oauth_login
from .online import (online_sign, query_certs, query_devices, ensure_cert,
                     delete_certs)


def _cred() -> tuple[str, str]:
    token = (oauth_dir() / "oauth2token.txt").read_text().strip()
    uid = (oauth_dir() / "uid.txt").read_text().strip()
    if not token:
        raise RuntimeError("缺少 oauth2Token，先运行 oauth-login")
    return token, uid


def cmd_check_env(_: argparse.Namespace) -> int:
    from .core import find_hdc, find_ohpm, find_hvigorw
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


def cmd_new_cert(_: argparse.Namespace) -> int:
    """确保证书材料就绪（幂等）：p12/CSR/云端证书/cloud.cer/cert-id.txt"""
    token, uid = _cred()
    cert_id, cer, p12 = ensure_cert(token, uid, None, None, None)
    print(f"\n证书材料就绪:")
    print(f"  certId : {cert_id}")
    print(f"  证书链 : {cer}")
    print(f"  私钥库 : {p12}（密码 123456, alias online-app）")
    print(f"  缓存   : {oauth_dir()/'work'/'cert-id.txt'}")
    return 0


def cmd_online(a: argparse.Namespace) -> int:
    online_sign(a.hap, a.bundle, a.cert_id, a.device_id, a.cert, a.p12, a.alias)
    return 0


def cmd_verify(a: argparse.Namespace) -> int:
    return 0 if verify_app(a.hap) else 1


def cmd_certs(a: argparse.Namespace) -> int:
    token, uid = _cred()
    cached = ""
    cid_file = oauth_dir() / "work" / "cert-id.txt"
    if cid_file.exists():
        cached = cid_file.read_text().strip()
    my_name = f"cli_debug_{uid}.cer"
    for c in query_certs(token, uid):
        mark = ""
        if str(c["id"]) == cached:
            mark = "  <- 本工具材料(work/cert-id.txt)"
        elif c.get("certName") == my_name:
            mark = "  <- 本工具同名证书"
        print(f"{c['id']}  {c['certName']}  {c.get('sha256','')[:16]}  expire={c.get('expireTime')}{mark}")
    print("\n提示: 本工具签发的证书无需记 id，online-sign 会自动复用（work/cert-id.txt）")
    return 0


def cmd_cert_delete(a: argparse.Namespace) -> int:
    """删除云端证书（清配额/清理不配对证书）。多个 id 用空格分隔"""
    token, uid = _cred()
    r = delete_certs(token, uid, a.ids)
    if r.get("ret", {}).get("code") == 0:
        print(f"✅ 已删除: {a.ids}")
        cid = oauth_dir() / "work" / "cert-id.txt"
        if cid.exists() and cid.read_text().strip() in a.ids:
            cid.unlink()
            print("   （已同步移除 work/cert-id.txt 缓存）")
        return 0
    print(f"❌ 删除失败: {json.dumps(r, ensure_ascii=False)[:300]}")
    return 1


def cmd_devices(a: argparse.Namespace) -> int:
    token, uid = _cred()
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

    sub.add_parser("new-cert", help="签发/复用云端调试证书（生成p12+CSR→cert/add→下载.cer）"
                   ).set_defaults(fn=cmd_new_cert)

    o = sub.add_parser("online-sign", help="在线签名 + 安装（certId/deviceId 可省略自动处理）")
    o.add_argument("hap"); o.add_argument("bundle")
    o.add_argument("cert_id", nargs="?", help="可选：云端证书 id（省略则自动签发/复用）")
    o.add_argument("device_id", nargs="?", help="可选：云端设备 id（省略则按 UDID 匹配/注册）")
    o.add_argument("--cert", help="云证书链 .cer"); o.add_argument("--p12", help="本地私钥库")
    o.add_argument("--alias", default="online-app"); o.set_defaults(fn=cmd_online)

    sub.add_parser("certs", help="列出云端证书").set_defaults(fn=cmd_certs)
    sub.add_parser("devices", help="列出云端设备").set_defaults(fn=cmd_devices)

    d = sub.add_parser("cert-delete", help="删除云端证书（清配额/清理不配对证书）")
    d.add_argument("ids", nargs="+", help="证书 id（certs 命令可查，多个用空格分隔）")
    d.set_defaults(fn=cmd_cert_delete)

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
