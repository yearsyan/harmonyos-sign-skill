"""在线自动签名（HarmonyOS 真机）：云端证书/Profile + 本地签名 + 安装"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .core import api_call, oauth_dir, run_java, KEYSTORE_PASS, hdc, subprocess, verify_app

CONNECT = "https://connect-api.cloud.huawei.com"
OBS = None  # 由 provisionFileUrl 动态获取

# 端点速查（★ 实测正确的路径，注意部分端点必须带 /add 等后缀）：
#   签发证书    POST   /api/cps/harmony-cert-manage/v1/cert/add   body={csr,certName,certType:"1"}
#   删除证书    DELETE /api/cps/harmony-cert-manage/v1/cert/delete body={certIds:[...]}
#               ★ 必须是 DELETE 方法（POST 会 404）；参数名 certIds（certId/ids 会报参数错误）
#   证书列表    POST   /api/cps/harmony-cert-manage/v1/cert/list   含 publicKeySha256（配对校验用）
#   下载URL     POST   /api/amis/app-manage/v1/objects/url/reapply body={sourceUrls:"<objectId|OBS url>"}
#               -> {urlsInfo:[{sourceUrl,newUrl,sha256}]}（OBS 预签名，300s 有效）
#   其余端点见 references/protocol.md


def _headers(token: str, uid: str) -> dict:
    return {"oauth2Token": token, "uid": uid, "teamId": uid}


def _connect_api(path: str, body: dict, token: str, uid: str, method: str = "POST") -> dict:
    return api_call(CONNECT + path, body, headers=_headers(token, uid), method=method)


def _connect_get(path: str, query: dict, token: str, uid: str) -> dict:
    import urllib.parse
    q = urllib.parse.urlencode(query)
    return api_call(f"{CONNECT}{path}?{q}", {}, headers=_headers(token, uid), method="GET")


def query_certs(token: str, uid: str) -> list[dict]:
    r = _connect_api("/api/cps/harmony-cert-manage/v1/cert/list", {}, token, uid)
    return r.get("certList", [])


def delete_certs(token: str, uid: str, cert_ids: list[str]) -> dict:
    """删除云端调试证书。★ DELETE 方法 + body 参数名 certIds（实测，2026-08）。
    POST 会 404；certId/ids/idList 等参数名会回 invalid parameters。
    非实名账号有证书配额（实测 3 张/账号），删除旧证书后才能签发新的。"""
    return _connect_api("/api/cps/harmony-cert-manage/v1/cert/delete",
                        {"certIds": [str(i) for i in cert_ids]}, token, uid, method="DELETE")


def cert_pubkey_fp(cert: dict) -> str:
    """归一化云端 publicKeySha256（形如 AA:BB:...）-> 小写 hex"""
    return str(cert.get("publicKeySha256") or "").replace(":", "").lower()


def p12_public_key_sha256(p12: Path, alias: str = "online-app",
                          pwd: str = KEYSTORE_PASS) -> str:
    """计算本地 p12 公钥指纹，与云端 cert/list.publicKeySha256 同口径：
    SHA256(base64(SPKI 中裸公钥点)) 的小写 hex。失败返回空串。
    优先用 openssl pkcs12 提取证书（无需 JDK keytool），失败时降级 keytool。
    用于校验本地 p12 与云端证书是否同一密钥对（换 p12/跨机迁移时避免签名报 keyAlias）。
    """
    import base64
    import hashlib

    def _from_pem(pem: str) -> str:
        pub = subprocess.run(["openssl", "x509", "-pubkey", "-noout"],
                             input=pem, capture_output=True, text=True, timeout=30)
        if pub.returncode != 0:
            return ""
        der = subprocess.run(["openssl", "pkey", "-pubin", "-outform", "DER"],
                             input=pub.stdout.encode(), capture_output=True, timeout=30)
        if der.returncode != 0:
            return ""
        # 剥 SPKI BIT STRING，取裸公钥点（去掉 unused-bits 计数字节）
        try:
            i = der.stdout.index(b"\x03")
            j = der.stdout[i + 1]
            if j & 0x80:
                n = j & 0x7f
                j = int.from_bytes(der.stdout[i + 2:i + 2 + n], "big")
                point = der.stdout[i + 2 + n:i + 2 + n + j]
            else:
                point = der.stdout[i + 2:i + 2 + j]
            return hashlib.sha256(base64.b64encode(point[1:])).hexdigest()
        except Exception:  # noqa: BLE001
            return ""

    try:
        # 1) openssl 直接读 p12（不依赖 JDK）：clcerts 导出证书链，取叶证书
        r = subprocess.run(["openssl", "pkcs12", "-in", str(p12),
                            "-passin", f"pass:{pwd}", "-clcerts", "-nokeys"],
                           capture_output=True, text=True, timeout=30)
        pem = r.stdout
        if r.returncode == 0 and "BEGIN CERTIFICATE" in pem:
            # 取最后一张（叶）证书，避免 openssl 输出头信息干扰
            certs = [c + "-----END CERTIFICATE-----\n"
                     for c in pem.split("-----END CERTIFICATE-----") if "BEGIN CERTIFICATE" in c]
            if certs:
                fp = _from_pem(certs[-1])
                if fp:
                    return fp
        # 2) 降级 keytool（JRE 无 keytool 时跳过）
        kt = subprocess.run(["keytool", "-exportcert", "-keystore", str(p12),
                             "-alias", alias, "-storepass", pwd, "-rfc"],
                            capture_output=True, text=True, timeout=30)
        if kt.returncode == 0 and "BEGIN CERTIFICATE" in kt.stdout:
            return _from_pem(kt.stdout)
    except Exception:  # noqa: BLE001
        pass
    return ""


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


def register_device(token: str, uid: str, udid: str, device_type: str = "phone",
                    name: str | None = None) -> dict:
    """注册设备（deviceType 取 hdc getprop hw_sc.build.os.devicetype，如 phone/2in1）"""
    r = _connect_api("/api/cps/device-manage/v1/device/add",
                     {"deviceName": name or f"cli_{udid[:8]}",
                      "udid": udid, "deviceType": device_type}, token, uid)
    return r


def reapply_download_url(token: str, uid: str, object_id: str) -> tuple[str, str]:
    """换取 OBS 预签名下载 URL（certObjectId / provisionFileUrl 均可）。
    返回 (newUrl, sha256)。sha256 可用于校验下载文件完整性。"""
    r = _connect_api("/api/amis/app-manage/v1/objects/url/reapply",
                     {"sourceUrls": object_id}, token, uid)
    urls = r.get("urlsInfo") or []
    if not urls:
        raise RuntimeError(f"reapply 换取下载URL失败: {json.dumps(r, ensure_ascii=False)[:300]}")
    return urls[0].get("newUrl", ""), urls[0].get("sha256", "")


def download(url: str, dest: Path) -> Path:
    import urllib.request
    with urllib.request.urlopen(url, timeout=30) as r:
        dest.write_bytes(r.read())
    return dest


# ---------------------------------------------------------------- 证书签发

def gen_keypair(p12: Path, alias: str = "online-app", pwd: str = KEYSTORE_PASS) -> None:
    """生成密钥对存入 p12。注意 -keySize 必须写全 NIST-P-384（写 N384 报 code=110 参数错误）"""
    run_java(["generate-keypair", "-keyAlias", alias, "-keyPwd", pwd,
              "-keystoreFile", str(p12), "-keystorePwd", pwd,
              "-keyAlg", "ECC", "-keySize", "NIST-P-384"])


def gen_csr(p12: Path, csr: Path, alias: str = "online-app", pwd: str = KEYSTORE_PASS) -> Path:
    """从 p12 生成 CSR。注意 -subject 必须是逗号分隔 "CN=xx, O=xx"（斜杠分隔报 code=101 格式错误）"""
    run_java(["generate-csr", "-keyAlias", alias, "-keyPwd", pwd,
              "-keystoreFile", str(p12), "-keystorePwd", pwd,
              "-signAlg", "SHA384withECDSA",
              "-subject", "CN=HarmonyOS Debug, O=Developer, OU=CLI",
              "-outFile", str(csr)])
    return csr


def issue_cert(token: str, uid: str, csr_pem: str, cert_name: str) -> dict:
    """上传 CSR 云端签发调试证书。★ 端点是 /cert/add（无 /add 后缀的 /cert 是 404）"""
    r = _connect_api("/api/cps/harmony-cert-manage/v1/cert/add",
                     {"csr": csr_pem, "certName": cert_name, "certType": "1"}, token, uid)
    cert = r.get("harmonyCert") or {}
    if not cert.get("id"):
        raise RuntimeError(f"证书签发失败: {json.dumps(r, ensure_ascii=False)[:300]}")
    return cert


def _local_udid() -> str | None:
    """读取本机已连接真机 UDID"""
    try:
        r = subprocess.run([str(hdc()), "shell", "bm", "get", "-u"],
                           capture_output=True, text=True, timeout=30)
        for line in r.stdout.splitlines():
            line = line.strip()
            if len(line) == 64 and all(c in "0123456789ABCDEFabcdef" for c in line):
                return line
    except Exception:  # noqa: BLE001
        pass
    return None


def find_device_by_udid(token: str, uid: str, udid: str) -> dict | None:
    """按 UDID 匹配云端已注册设备（云端列表 udid 为完整值，做前缀匹配兜底）"""
    for d in query_devices(token, uid):
        if d.get("udid", "").lower().startswith(udid[:16].lower()):
            return d
    return None


def ensure_device(token: str, uid: str, device_id: str | None) -> str:
    """解析出可用的云端 deviceId：显式传入 > UDID 匹配 > 自动注册"""
    if device_id:
        return device_id
    udid = _local_udid()
    if not udid:
        raise RuntimeError("未检测到已连接设备（hdc shell bm get -u 无输出）。"
                           "请连接设备或显式传入 deviceId")
    d = find_device_by_udid(token, uid, udid)
    if d:
        print(f"   ✅ 匹配云端设备: {d['id']} ({d.get('deviceName','')})")
        return d["id"]
    # 未注册 -> 尝试注册（deviceType 读取系统属性，兜底 phone）
    dtype = "phone"
    try:
        r = subprocess.run([str(hdc()), "shell", "getprop", "hw_sc.build.os.devicetype"],
                           capture_output=True, text=True, timeout=30)
        if r.stdout.strip():
            dtype = r.stdout.strip()
    except Exception:  # noqa: BLE001
        pass
    r = register_device(token, uid, udid, dtype)
    new_id = (r.get("deviceInfo") or {}).get("id") or r.get("id")
    if not new_id:
        raise RuntimeError(f"设备注册失败: {json.dumps(r, ensure_ascii=False)[:300]}（也可到"
                           "AGC 手动注册后用 devices 命令查 id）")
    print(f"   ✅ 已注册设备: {new_id}")
    return str(new_id)


def ensure_cert(token: str, uid: str, cert_id: str | None,
                cert_cer: Path | None, key_p12: Path | None) -> tuple[str, Path, Path]:
    """确保证书材料就绪。返回 (certId, cloud.cer, online-app.p12)。

    优先级：显式 certId > work/cert-id.txt（校验配对）> 云端指纹匹配 > 自动清理旧证书后重签。
    配对校验：本地 p12 公钥指纹 vs 云端 publicKeySha256（同口径 SHA256(base64(裸公钥点))）。
    不配对场景（换机器/删了 p12/缓存过期）自动处理：
      - 删除云端不配对的本工具证书（cli_debug_<uid>.cer，占配额且无法使用）
      - 签发失败（通常是非实名证书配额满，实测 3 张/账号）时清理可删证书后重试一次
    """
    od = oauth_dir()
    work = od / "work"
    work.mkdir(parents=True, exist_ok=True)
    p12 = Path(key_p12) if key_p12 else work / "online-app.p12"
    cer = Path(cert_cer) if cert_cer else work / "cloud.cer"
    cert_id_file = work / "cert-id.txt"
    my_name = f"cli_debug_{uid}.cer"

    def _fp_match(c: dict) -> bool:
        fp = cert_pubkey_fp(c)
        return bool(local_fp and fp and fp == local_fp)

    if cert_id:  # 显式指定，证书文件必须同时存在
        if not cer.exists():
            raise RuntimeError(f"指定了 certId={cert_id} 但缺少证书文件 {cer}"
                               "（先运行 new-cert 或手动下载）")
        if not p12.exists():
            raise RuntimeError(f"指定了 certId={cert_id} 但缺少私钥库 {p12}")
        return cert_id, cer, p12

    if not p12.exists():
        print("   ⚙️ 生成密钥对 (ECC NIST-P-384) -> online-app.p12")
        gen_keypair(p12)

    local_fp = p12_public_key_sha256(p12)
    if local_fp:
        print(f"   🔑 本地 p12 公钥指纹: {local_fp[:20]}...")

    def _cleanup_stale(certs: list[dict], reason: str) -> int:
        """删除不配对的本工具(cli_debug_*)旧证书，返回删除数量"""
        stale = [c for c in certs
                 if c.get("certName") == my_name and not _fp_match(c)
                 and c.get("allowDel", 1)]
        if not stale:
            return 0
        ids = [str(c["id"]) for c in stale]
        print(f"   🧹 {reason}: 删除不配对旧证书 {ids}")
        r = delete_certs(token, uid, ids)
        if r.get("ret", {}).get("code") != 0:
            print(f"   ⚠️ 删除失败: {json.dumps(r, ensure_ascii=False)[:200]}")
            return 0
        return len(stale)

    # 1) 本工具缓存的 certId（需通过配对校验；不配对视为无效缓存）
    if cert_id_file.exists():
        cached = cert_id_file.read_text().strip()
        if cached and cer.exists():
            certs = query_certs(token, uid)
            hit = next((c for c in certs if str(c.get("id")) == cached), None)
            if hit and _fp_match(hit):
                print(f"   ✅ 复用已签发证书: {cached}")
                return cached, cer, p12
            if hit:
                print(f"   ⚠️ 缓存证书 {cached} 与本地 p12 不配对"
                      f"（云端 {cert_pubkey_fp(hit)[:16]}... vs 本地 {local_fp[:16] if local_fp else '?'}...），忽略缓存")
            else:
                print(f"   ⚠️ 缓存的 certId {cached} 云端不存在，忽略缓存")

    # 2) 云端按公钥指纹匹配（跨机迁移：p12 还在、缓存丢失时自动找回对应证书）
    certs = query_certs(token, uid)
    for c in certs:
        if _fp_match(c):
            url, _ = reapply_download_url(token, uid, c["certObjectId"])
            download(url, cer)
            cert_id_file.write_text(str(c["id"]))
            print(f"   ✅ 按指纹匹配到配对证书 {c['id']} ({c.get('certName','')})，重新下载 .cer")
            return str(c["id"]), cer, p12

    # 3) 清理不配对的本工具旧证书（占配额），然后签发新证书
    _cleanup_stale(certs, "清理不配对旧证书")
    csr = work / "online-app.csr"
    gen_csr(p12, csr)
    print(f"   ⚙️ 上传 CSR 签发证书 {my_name} ...")
    try:
        cert = issue_cert(token, uid, csr.read_text(), my_name)
    except RuntimeError:
        # 签发失败（通常是配额满）：再清一轮可删证书后重试一次
        certs = query_certs(token, uid)
        removable = [c for c in certs if c.get("allowDel", 1) and not _fp_match(c)]
        ids = [str(c["id"]) for c in removable[:2]]
        if not ids:
            raise
        print(f"   🧹 签发失败，清理可删证书 {ids} 后重试 ...")
        r = delete_certs(token, uid, ids)
        if r.get("ret", {}).get("code") != 0:
            raise RuntimeError(
                f"证书配额满且删除失败: {json.dumps(r, ensure_ascii=False)[:200]}。"
                "可用 cert-delete 命令手动清理云端证书")
        cert = issue_cert(token, uid, csr.read_text(), my_name)
    url, _ = reapply_download_url(token, uid, cert["certObjectId"])
    download(url, cer)
    cert_id_file.write_text(str(cert["id"]))
    print(f"   ✅ 新证书签发成功: {cert['id']}，.cer 已下载 ({cer.stat().st_size} B)")
    return str(cert["id"]), cer, p12


def _sign(hap_in: str, cert: Path, prov: Path, p12: Path, alias: str, hap_out: str) -> str:
    run_java(["sign-app", "-mode", "localSign",
              "-keyAlias", alias, "-keyPwd", KEYSTORE_PASS,
              "-appCertFile", str(cert), "-profileFile", str(prov),
              "-inFile", hap_in, "-signAlg", "SHA384withECDSA",
              "-keystoreFile", str(p12), "-keystorePwd", KEYSTORE_PASS,
              "-outFile", hap_out, "-signCode", "1"])
    return hap_out


def online_sign(hap_in: str, bundle: str, cert_id: str | None, device_id: str | None,
                cert_cer: str | None = None, key_p12: str | None = None,
                key_alias: str = "online-app") -> str:
    """在线签名全流程。cert_id/device_id 可省略（自动签发/匹配）。
    cert_cer: 云证书链文件(.cer)；key_p12: 本地私钥库"""
    od = oauth_dir()
    work = od / "work"
    work.mkdir(parents=True, exist_ok=True)
    token = (od / "oauth2token.txt").read_text().strip()
    uid = (od / "uid.txt").read_text().strip()
    if not token:
        raise RuntimeError("缺少 oauth2Token，先运行 oauth-login")

    # 0. 证书材料（自动签发/复用）
    print("== 1/4 证书材料")
    cert_id, cert, p12 = ensure_cert(token, uid, cert_id,
                                     Path(cert_cer) if cert_cer else None,
                                     Path(key_p12) if key_p12 else None)

    # 1. 设备（自动匹配/注册）
    print("== 2/4 设备")
    device_id = ensure_device(token, uid, device_id)

    # 2. 创建调试 Profile
    print("== 3/4 创建调试 Profile")
    r = create_provision(token, uid, cert_id, bundle, device_id)
    url = r.get("provisionFileUrl", "")
    if not url:
        raise RuntimeError(f"Profile 创建失败: {json.dumps(r, ensure_ascii=False)[:300]}")
    prov = download(url, work / "profile.p7b")
    print(f"   ✅ profile.p7b ({prov.stat().st_size} B)")

    # 3. 本地签名
    print("== 4/4 本地签名 + 验证 + 安装")
    hap_out = hap_in[:-4] + "-cloud-signed.hap"
    _sign(hap_in, cert, prov, p12, key_alias, hap_out)
    print(f"   ✅ 已签名: {hap_out}")

    verify_app(hap_out)

    r = subprocess.run([str(hdc()), "install", "-r", hap_out],
                       capture_output=True, text=True, timeout=120)
    ok = "successfully" in (r.stdout + r.stderr)
    print((f"✅ 安装完成: {hap_out}" if ok
           else f"❌ 安装失败: {(r.stdout + r.stderr)[-300:]}"))
    if not ok:
        raise RuntimeError("hdc install 失败")
    return hap_out
