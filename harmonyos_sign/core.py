"""HarmonyOS signing toolkit - 工具链自动发现与 Java/HTTP 封装（纯标准库）

hdc / ohpm / hvigor / hap-sign-tool.jar 的位置按以下顺序自动发现：
  1. 环境变量 HOS（command-line-tools 根）或 DEVECO_SDK_HOME / HOS_SDK_HOME / OHOS_SDK_HOME（sdk 根）
  2. PATH 中已有的 hdc（which hdc）
  3. 各平台 DevEco Studio / Command Line Tools 常见安装目录：
     - Linux:   ~/deveco*, ~/harmonyos*, ~/ohos*, /opt/..., /usr/local/...
     - macOS:   /Applications/DevEco-Studio.app/Contents/sdk/..., ~/Applications/...
     - Windows: C:\\Program Files\\Huawei\\DevEco Studio\\sdk\\...,
                %LOCALAPPDATA%\\Huawei\\...
  4. 关键词（deveco/harmonyos/ohos/huawei/command-line-tools）浅层递归扫描
"""
from __future__ import annotations

import functools
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

KEYSTORE_PASS = "123456"


def _git_ignore(dir_: Path) -> None:
    """若 dir_ 位于 git 仓库内，把 .ohos-sign/ 追加到仓库根 .gitignore（防私钥误提交）"""
    try:
        root = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                              capture_output=True, text=True, timeout=10,
                              cwd=str(dir_)).stdout.strip()
        if not root:
            return
        rel = dir_.resolve().relative_to(Path(root).resolve())
        pattern = rel.as_posix() + "/" if str(rel) != "." else ".ohos-sign/"
        gi = Path(root) / ".gitignore"
        existing = gi.read_text().splitlines() if gi.exists() else []
        if pattern in existing or pattern.rstrip("/") in existing:
            return
        with open(gi, "a") as f:
            if existing and not existing[-1].endswith(("\n", "\r")):
                f.write("\n")
            f.write(pattern + "\n")
    except Exception:  # noqa: BLE001
        pass


def _find_project_root(start: Path) -> Path:
    """向上查找鸿蒙工程根（含 build-profile.json5）；找不到返回 start"""
    for d in (start, *start.parents):
        if (d / "build-profile.json5").exists():
            return d
    return start


def oauth_dir() -> Path:
    """持久签名材料目录：跟随鸿蒙项目，避免在家目录留下残余。
    位置：最近工程根（含 build-profile.json5）或当前目录下的 `.ohos-sign/`；
    git 仓库（rev-parse 命中）自动把 `.ohos-sign/` 写入 .gitignore。
    环境变量 OHOS_OAUTH 显式覆盖。
    旧版 ~/.ohos-oauth/work 材料自动迁移（一次性）。"""
    override = os.environ.get("OHOS_OAUTH")
    if override:
        p = Path(override)
    else:
        p = _find_project_root(Path.cwd()) / ".ohos-sign"
    p.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        p.chmod(0o700)
    except OSError:
        pass
    if not override:
        _git_ignore(p)
    # 一次性迁移：旧 ~/.ohos-oauth/work -> .ohos-sign/work
    try:
        old = Path(os.environ.get("OHOS_OAUTH", "~/.ohos-oauth")).expanduser() / "work"
        if old.exists() and not (p / "work").exists() and any(old.iterdir()):
            shutil.move(str(old), str(p / "work"))
    except Exception:  # noqa: BLE001
        pass
    return p


def token_dir() -> Path:
    """临时会话凭证目录（oauth2token/jwt/uid）：oauth2Token 约 1h 过期，属临时数据，
    不落磁盘持久目录。优先 $XDG_RUNTIME_DIR（/run/user/<uid>，系统自动清理），
    回退 /tmp；按 uid 区分，权限 0700。可用环境变量 OHOS_TOKEN 覆盖。"""
    override = os.environ.get("OHOS_TOKEN")
    if override:
        p = Path(override)
    else:
        base = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
        p = Path(base) / f"ohos-sign-token-{os.getuid()}"
    p.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        p.chmod(0o700)
    except OSError:
        pass
    # 一次性迁移：旧位置（~/.ohos-oauth）若仍有 token 且新位置没有，搬过去
    # ★ 用 shutil.move：/run/user (tmpfs) 与 /root 跨文件系统，rename 会 EXDEV
    for name in ("oauth2token.txt", "jwt.txt", "uid.txt"):
        old = Path(os.environ.get("OHOS_OAUTH", "~/.ohos-oauth")).expanduser() / name
        if old.exists() and not (p / name).exists() and not override:
            try:
                shutil.move(str(old), str(p / name))
            except Exception:  # noqa: BLE001
                pass
    return p

# ---------------------------------------------------------------- 候选目录


def _env_candidates() -> list[Path]:
    cands = []
    # command-line-tools 根
    for e in ("HOS", "HOS_HOME", "HARMONYOS_HOME", "DEVECO_HOME"):
        v = os.environ.get(e)
        if v:
            cands.append(Path(v).expanduser())
    # sdk 根（DevEco 标准变量，含 default/openharmony/toolchains）
    for e in ("DEVECO_SDK_HOME", "HOS_SDK_HOME", "OHOS_SDK_HOME"):
        v = os.environ.get(e)
        if v:
            cands.append(Path(v).expanduser())
    # PATH 中已有的 hdc
    for name in ("hdc", "hdc.exe"):
        h = shutil.which(name)
        if h:
            cands.append(Path(h).resolve())
    return cands


def _platform_homes() -> list[Path]:
    homes = []
    if sys.platform == "win32":
        for v in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            p = os.environ.get(v)
            if p:
                homes.append(Path(p))
    else:
        homes = [Path.home(), Path("/opt"), Path("/usr/local"), Path("/Applications")]
        if sys.platform == "darwin":
            homes.append(Path.home() / "Applications")
    return homes


_KEYWORDS = ("deveco", "harmony", "ohos", "huawei", "command-line-tools", "commandline")

# 各平台 DevEco SDK 的固定已知位置（直接探测，避免全盘扫描）
_KNOWN_DIRS = [
    "~/Library/OpenHarmony",                 # macOS: DevEco SDK 默认目录
    "~/Library/Huawei",
    "~/Library/Application Support/Huawei",
    "~/Library/Application Support/OpenHarmony",
]


def _keyword_candidates() -> list[Path]:
    """常见安装根下按关键词枚举候选目录（仅一层）"""
    cands = []
    for home in _platform_homes():
        if not home.exists():
            continue
        try:
            for sub in home.iterdir():
                if sub.is_dir() and any(k in sub.name.lower() for k in _KEYWORDS):
                    cands.append(sub)
        except OSError:
            continue
    # macOS ~/Library 一层（OpenHarmony/Huawei 等 SDK 目录）
    lib = Path.home() / "Library"
    if lib.exists():
        try:
            for sub in lib.iterdir():
                if sub.is_dir() and any(k in sub.name.lower() for k in _KEYWORDS):
                    cands.append(sub)
        except OSError:
            pass
    # 固定已知位置
    for p in _KNOWN_DIRS:
        cands.append(Path(p).expanduser())
    return cands


def _candidates() -> list[Path]:
    return _env_candidates() + _keyword_candidates()


# ---------------------------------------------------------------- hdc 定位

def _hdc_at(root: Path) -> Path | None:
    """检查一个候选目录下是否存在 hdc（常见布局）"""
    if root.name in ("hdc", "hdc.exe") and root.exists():
        return root
    layouts = [
        "sdk/default/openharmony/toolchains/hdc",      # Command Line Tools 布局
        "sdk/default/openharmony/toolchains/hdc.exe",
        "default/openharmony/toolchains/hdc",          # DEVECO_SDK_HOME 直接指向 default 上级
        "default/openharmony/toolchains/hdc.exe",
        "openharmony/toolchains/hdc",                  # 旧 SDK 布局
        "openharmony/toolchains/hdc.exe",
        "toolchains/hdc",                              # 候选目录即 SDK 版本目录
        "toolchains/hdc.exe",
        "sdk/openharmony/toolchains/hdc",              # 部分版本布局
        "sdk/openharmony/toolchains/hdc.exe",
        "Contents/sdk/default/openharmony/toolchains/hdc",   # macOS .app
        "Contents/sdk/default/openharmony/toolchains/hdc.exe",
        "Contents/toolchains/hdc",                     # macOS .app 备选
        "Contents/toolchains/hdc.exe",
    ]
    for rel in layouts:
        p = root / rel
        if p.exists():
            return p
    # macOS DevEco SDK 版本目录: <root>/Sdk/<版本或代号>/toolchains|openharmony/toolchains/hdc
    for sdk_name in ("Sdk", "sdk"):
        sdk_dir = root / sdk_name
        if not sdk_dir.is_dir():
            continue
        try:
            for ver in sdk_dir.iterdir():
                if not ver.is_dir():
                    continue
                for rel in ("toolchains/hdc", "toolchains/hdc.exe",
                            "openharmony/toolchains/hdc", "openharmony/toolchains/hdc.exe"):
                    p = ver / rel
                    if p.exists():
                        return p
        except OSError:
            continue
    return None


def _scan_shallow(d: Path, depth: int = 3) -> Path | None:
    """浅层递归找 toolchains/hdc（限制深度，跳过隐藏/大目录）"""
    if depth <= 0 or not d.exists():
        return None
    _SKIP = {"Library", ".cache", "node_modules", "Applications", ".Trash"}
    try:
        for sub in d.iterdir():
            if not sub.is_dir() or sub.name.startswith(".") or sub.name in _SKIP:
                continue
            h = _hdc_at(sub)
            if h:
                return h
            r = _scan_shallow(sub, depth - 1)
            if r:
                return r
    except OSError:
        pass
    return None


@functools.lru_cache(maxsize=1)
def find_hdc() -> Path | None:
    """自动发现 hdc 可执行文件路径"""
    for c in _candidates():
        h = _hdc_at(c)
        if h:
            return h
    # 关键词目录浅层扫描（避免全盘扫描）
    for home in _platform_homes():
        h = _scan_shallow(home, depth=3)
        if h:
            return h
    return None


# ---------------------------------------------------------------- 导出 API

def toolchains_dir() -> Path:
    h = find_hdc()
    if h is None:
        sys.exit("错误: 未找到 hdc。请安装 HarmonyOS Command Line Tools 或 DevEco Studio，"
                 "或设置环境变量 HOS=<command-line-tools根> / DEVECO_SDK_HOME=<sdk根>")
    return h.parent


def hap_sign_jar() -> Path:
    j = toolchains_dir() / "lib" / "hap-sign-tool.jar"
    if not j.exists():
        sys.exit(f"错误: 未找到 hap-sign-tool.jar: {j}")
    return j


def hdc() -> Path:
    h = find_hdc()
    if h is None:
        sys.exit("错误: 未找到 hdc。请安装工具链或设置 HOS/DEVECO_SDK_HOME 环境变量")
    return h


def clt_root() -> Path | None:
    """尝试推导 Command Line Tools 根（toolchains 上溯 4 级: toolchains->openharmony->default->sdk->root）"""
    t = toolchains_dir()
    try:
        root = t.parents[4]  # 需要 toolchains/openharmony/default/sdk/root 结构
        if (root / "bin").exists():
            return root
    except IndexError:
        pass
    env = os.environ.get("HOS")
    return Path(env).expanduser() if env else None


def sdk_root() -> Path | None:
    """推导 sdk 根（toolchains 上溯 3 级）"""
    t = toolchains_dir()
    try:
        return t.parents[3]
    except IndexError:
        return None


def find_ohpm() -> Path | None:
    for name in ("ohpm", "ohpm.exe"):
        p = shutil.which(name)
        if p:
            return Path(p)
    for d in (clt_root(), sdk_root()):
        if not d:
            continue
        for rel in ("bin/ohpm", "ohpm/bin/ohpm", "tools/ohpm/bin/ohpm"):
            p = d / rel
            if p.exists():
                return p
    return None


def find_hvigorw() -> Path | None:
    for name in ("hvigorw", "hvigorw.exe"):
        p = shutil.which(name)
        if p:
            return Path(p)
    for d in (clt_root(), sdk_root()):
        if not d:
            continue
        for rel in ("bin/hvigorw", "hvigor/bin/hvigorw", "tools/hvigor/bin/hvigorw"):
            p = d / rel
            if p.exists():
                return p
    return None


def describe_toolchain() -> str:
    """打印发现的工具链信息（供 check-env 展示）"""
    lines = []
    h = find_hdc()
    lines.append(f"hdc       : {h or '未找到'}")
    j = toolchains_dir() / "lib/hap-sign-tool.jar" if h else None
    lines.append(f"sign-tool : {j if j and j.exists() else '未找到'}")
    lines.append(f"ohpm      : {find_ohpm() or '未找到'}")
    lines.append(f"hvigorw   : {find_hvigorw() or '未找到'}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 基础工具

def run(cmd: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def run_java(args: list[str], quiet: bool = True) -> str:
    """运行 hap-sign-tool.jar"""
    full = ["java", "-jar", str(hap_sign_jar())] + args
    r = run(full)
    if r.returncode != 0 or (not quiet and r.stderr):
        err = r.stdout[-400:] + r.stderr[-400:]
        raise RuntimeError(f"hap-sign-tool 失败: {err}")
    return r.stdout


def api_call(url: str, body: dict, headers: dict | None = None, method: str = "POST") -> dict:
    """HTTP JSON 调用（标准库 urllib）"""
    import urllib.request
    import urllib.error

    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "Chrome/49.0.2623.75")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"_raw": raw}
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code, "_raw": e.read().decode(errors="replace")}
    except Exception as e:  # noqa: BLE001
        return {"_error": str(e)}


def verify_app(hap: str) -> bool:
    """验证 HAP 签名"""
    out = run_java(["verify-app", "-inFile", hap,
                    "-outCertChain", "/tmp/_vc.cer", "-outProfile", "/tmp/_vp.p7b"])
    ok = "Verify success" in out or "verify-app success" in out
    print(f"{'✅' if ok else '❌'} verify: {'Verify success' if ok else out[-200:]}")
    return ok
