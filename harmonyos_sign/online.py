"""在线自动签名（HarmonyOS 真机）：云端证书/Profile + 本地签名 + 安装"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .core import api_call, oauth_dir, run_java, KEYSTORE_PASS, hdc, subprocess, verify_app

CONNECT = "https://connect-api.cloud.huawei.com"
OBS = None  # 由 provisionFileUrl 动态获取


def _headers(token: str, uid: str) -> dict:
    return {"oauth2Token": token, "uid": uid, "teamId": uid}


def _connect_api(path: str, body: dict, token: str, uid: str) -> dict:
    return api_call(CONNECT + path, body, headers=_headers(token, uid))


def _connect_get(path: str, query: dict, token: str, uid: str) -> dict:
    import urllib.parse
    q = urllib.parse.urlencode(query)
    return api_call(f"{CONNECT}{path}?{q}", {}, headers=_headers(token, uid), method="GET")


def query_certs(token: str, uid: str) -> list[dict]:
    r = _connect_api("/api/cps/harmony-cert-manage/v1/cert/list", {}, token, uid)
    return r.get("certList", [])


def query_devices(token: str, uid: str) -> list[dict]:
    r = _connect_get("/api/cps/device-manage/v1/device/list",
                     {"encodeFlag": "0", "start": 1, "pageSize": 100}, token, uid)
    return r.get("list") or r.get("deviceInfos") or []


def create_provision(token: str, uid: str, cert_id: str, bundle: str,
                     device_id: str, name: str | None = None) -> dict:
    """创建调试 Profile（★ deviceList 传 deviceId 字符串）"""
    r = _connect_api("/api/cps/provision-manage/v1/ide/test/provision/add",
                     {"certList": [cert_id], "packageName": bundle,
                      "deviceList": [device_id],
                      "provisionName": name or f"auto_{bundle.split('.')[-1]}_{int(time.time())}",
                      "aclPermissionList": []}, token, uid)
    return r


def download(url: str, dest: Path) -> Path:
    import urllib.request
    with urllib.request.urlopen(url, timeout=30) as r:
        dest.write_bytes(r.read())
    return dest


def _sign(hap_in: str, cert: Path, prov: Path, p12: Path, alias: str, hap_out: str) -> str:
    run_java(["sign-app", "-mode", "localSign",
              "-keyAlias", alias, "-keyPwd", KEYSTORE_PASS,
              "-appCertFile", str(cert), "-profileFile", str(prov),
              "-inFile", hap_in, "-signAlg", "SHA384withECDSA",
              "-keystoreFile", str(p12), "-keystorePwd", KEYSTORE_PASS,
              "-outFile", hap_out, "-signCode", "1"])
    return hap_out


def online_sign(hap_in: str, bundle: str, cert_id: str, device_id: str,
                cert_cer: str | None = None, key_p12: str | None = None,
                key_alias: str = "online-app") -> str:
    """在线签名全流程。cert_cer: 云证书链文件(.cer)；key_p12: 本地私钥库"""
    od = oauth_dir()
    work = od / "work"
    work.mkdir(parents=True, exist_ok=True)
    token = (od / "oauth2token.txt").read_text().strip()
    uid = (od / "uid.txt").read_text().strip()
    if not token:
        raise RuntimeError("缺少 oauth2Token，先运行 oauth-login")

    # 1. 创建调试 Profile
    print("== 1/4 创建调试 Profile")
    r = create_provision(token, uid, cert_id, bundle, device_id)
    url = r.get("provisionFileUrl", "")
    if not url:
        raise RuntimeError(f"Profile 创建失败: {json.dumps(r, ensure_ascii=False)[:300]}")
    prov = download(url, work / "profile.p7b")
    print(f"   ✅ profile.p7b ({prov.stat().st_size} B)")

    # 2. 证书
    print("== 2/4 云证书")
    cert = Path(cert_cer) if cert_cer else work / "cloud.cer"
    if not cert.exists():
        raise RuntimeError("缺少云证书 .cer（可先手动下载到 work/cloud.cer）")
    print(f"   ✅ {cert}")

    # 3. 本地签名
    print("== 3/4 本地签名")
    hap_out = hap_in[:-4] + "-cloud-signed.hap"
    p12 = Path(key_p12) if key_p12 else od / "online-app.p12"
    if not p12.exists():
        raise RuntimeError(f"缺少本地私钥库 {p12}（需与云证书匹配）")
    _sign(hap_in, cert, prov, p12, key_alias, hap_out)

    # 4. 验证 + 安装
    print("== 4/4 验证 + 安装")
    if not verify_app(hap_out):
        raise RuntimeError("签名验证失败")
    r = subprocess.run([str(hdc()), "install", "-r", hap_out],
                       capture_output=True, text=True, timeout=120)
    print(r.stdout.strip()[-200:] or r.stderr.strip()[-200:])
    return hap_out
