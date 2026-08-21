# harmonyos-sign

HarmonyOS 应用签名与真机安装工具链（Python，零第三方依赖）。

在无 DevEco（Linux 无官方版）环境下，通过模拟 DevEco 客户端 OAuth 登录，完成
**云端签发证书/调试 Profile → 本地 HAP 签名 → hdc 安装真机**的完整闭环。
浏览器授权由 agent 自主选择工具完成（Kimi WebBridge / Chrome DevTools MCP / Playwright 等），
脚本只负责生成授权 URL 与等待回调。未实名华为账号同样可用。

> 命名说明：HarmonyOS 5.0 起官方统一称 **HarmonyOS**（早期版本曾称 HarmonyOS NEXT）。

## 功能

| 命令 | 说明 |
|------|------|
| `check-env` | 工具链自动发现 + 环境检查 |
| `fetch-udid` | 读取已连接真机 UDID |
| `oauth-login` | 生成授权 URL，等待回调并兑换 oauth2Token（默认 5min 超时） |
| `online-sign` | 云端创建调试 Profile + 本地签名 + hdc 安装 |
| `certs` / `devices` | 查询云端证书 / 已注册设备 |
| `verify` | 验证 HAP 签名 |

## 安装

### 方式 1：pi install（推荐给 pi 用户）

```bash
# 公开仓库
pi install git:github.com/yearsyan/harmonyos-sign-skill

# 私有仓库（用 SSH，需已配置 GitHub key）
pi install git:git@github.com:yearsyan/harmonyos-sign-skill
```

安装后 skill 自动注册为 `/skill:harmonyos-signing`，pi 在相关任务中会自动加载。

### 方式 2：手动 clone 到 pi skills 目录

```bash
git clone git@github.com:yearsyan/harmonyos-sign-skill.git ~/.pi/agent/skills/harmonyos-signing
# 或全局 skills 目录: ~/.agents/skills/
```

### 方式 3：作为 Python 工具使用

```bash
# 零安装：仓库目录内直接运行
cd harmonyos-sign-skill && python3 -m harmonyos_sign check-env

# 虚拟环境安装（隔离，推荐）
python3 -m venv .venv && .venv/bin/pip install -e . && .venv/bin/harmonyos-sign check-env

# 用户级安装（不进系统 site-packages）
pip install -e . --user
```

> 不建议裸 `pip install -e .`（会写入当前 Python 环境的全局 site-packages）。

### 方式 4：安装到其他 Agent 工具（Claude Code / Codex / Kimi Code / ZCode）

本项目遵循 [Agent Skills 标准](https://agentskills.io/specification)（SKILL.md + frontmatter），
各工具安装方式 = 把仓库 clone 到其 skills 目录：

| 工具 | skills 目录 | 手动安装命令 |
|------|------------|-------------|
| Claude Code | `~/.claude/skills/` | `git clone <repo> ~/.claude/skills/harmonyos-signing` |
| Codex CLI | `~/.codex/skills/` | `git clone <repo> ~/.codex/skills/harmonyos-signing` |
| Kimi Code | `$KIMI_CODE_HOME/skills/`（默认 `~/.kimi-code/skills/`） | `git clone <repo> ~/.kimi-code/skills/harmonyos-signing` |
| ZCode | `~/.zcode/skills/` | `git clone <repo> ~/.zcode/skills/harmonyos-signing` |
| pi | `~/.pi/agent/skills/` | `pi install git:github.com/yearsyan/harmonyos-sign-skill` |

**一键安装**（公开仓库，无需 git，自动检测已安装的工具并逐个安装/更新）：

```bash
# 推荐：远程安装（curl 管道，无需 clone）
curl -sL https://raw.githubusercontent.com/yearsyan/harmonyos-sign-skill/main/install.sh | bash

# 或 clone 后本地执行
#   ./install.sh <git-url>   指定仓库
#   ./install.sh --local     离线（从当前目录复制）
```

> 提示：ZCode 安装后需在 Settings -> Skills 点击 Refresh；各工具重启会话后
> 通过 `/skill:harmonyos-signing` 调用。

## 快速开始

```bash
# 1. 检查环境（自动发现 hdc/ohpm/hvigor/hap-sign-tool.jar）
python3 -m harmonyos_sign check-env

# 2. 构建 unsigned HAP（需 HarmonyOS 工程）
hvigorw assembleHap --mode module -p product=default -p buildMode=debug --no-daemon

# 3. 登录取 oauth2Token —— 脚本打印授权 URL，agent 用浏览器工具打开并点「允许」
python3 -m harmonyos_sign oauth-login --timeout 300

# 4. 查询云端证书/设备
python3 -m harmonyos_sign certs
python3 -m harmonyos_sign devices

# 5. 在线签名 + 安装
python3 -m harmonyos_sign online-sign app-unsigned.hap com.example.app <certId> <deviceId> \
    --cert cloud.cer --p12 online-app.p12

# 6. 启动验证
python3 -m harmonyos_sign verify app-cloud-signed.hap
hdc shell aa start -a EntryAbility -b com.example.app
```

## 工具链自动发现（零配置）

hdc / ohpm / hvigor / hap-sign-tool.jar 按以下顺序自动发现：

1. **环境变量**：`HOS`（command-line-tools 根）、`DEVECO_SDK_HOME` / `HOS_SDK_HOME` / `OHOS_SDK_HOME`（sdk 根）
2. **PATH**：`which hdc`
3. **常见安装目录**（关键词扫描）：
   - Linux：`~/deveco*` `~/harmonyos*` `~/ohos*` `/opt/*` `/usr/local/*`
   - macOS：`~/Library/OpenHarmony`（DevEco SDK 默认目录）、`/Applications/DevEco-Studio.app/Contents/sdk/...`
   - Windows：`C:\Program Files\Huawei\DevEco Studio\sdk\...`、`%LOCALAPPDATA%\Huawei\...`
4. **支持布局**：
   - Command Line Tools：`<root>/sdk/default/openharmony/toolchains/hdc`
   - macOS DevEco SDK：`~/Library/OpenHarmony/Sdk/<版本>/toolchains/hdc` 或 `.../openharmony/toolchains/hdc`
   - 旧版 SDK：`<sdk>/openharmony/toolchains/hdc`
   - macOS .app：`DevEco-Studio.app/Contents/sdk/default/...`

`check-env` 会打印实际发现路径。

## 架构与原理

```
浏览器授权（agent 工具）        Python 脚本（harmonyos_sign）
┌─────────────────────┐      ┌──────────────────────────────────┐
│ 打开授权 URL         │ ───▶ │ oauth-login: 生成 URL + 等待回调  │
│ 检查登录→点击允许    │      │  tempToken → jwtToken → oauth2Token│
└─────────────────────┘      └──────────────┬───────────────────┘
                                            ▼
                            connect-api.cloud.huawei.com（oauth2Token 认证）
                            创建调试 Profile（ide/test/provision/add）
                            查询证书 / 注册设备
                                            ▼
                            hap-sign-tool.jar 本地签名（SHA-384/ECDSA）
                            hdc install → aa start
```

关键协议细节见 [references/protocol.md](references/protocol.md)。

## 环境要求

- Python 3.9+（仅标准库）
- Java（运行 hap-sign-tool.jar）
- HarmonyOS Command Line Tools 或 DevEco Studio 安装的 SDK（hdc + hap-sign-tool.jar）
- Linux 连接真机需 udev 规则（vendor 12d1）：`/etc/udev/rules.d/51-harmonyos.rules`

## 安全说明

- 涉及华为账号 OAuth 授权与签名证书，仅限个人开发者调试用途
- oauth2Token 有效期约 1 小时，保存在 `~/.ohos-oauth/`（注意权限保护）
- 请勿提交私钥/证书/token 到仓库

## License

MIT
