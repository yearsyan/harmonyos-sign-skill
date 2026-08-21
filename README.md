# harmonyos-sign-skill

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
| `new-cert` | 签发/复用云端调试证书：本地 p12+CSR → `cert/add` 签发 → 下载 .cer（幂等） |
| `online-sign` | 一键签名+安装：证书自动签发/复用、设备自动匹配/注册、创建 Profile、本地签名、hdc 安装（certId/deviceId 可省略） |
| `certs` / `devices` | 查询云端证书（标记本工具材料）/ 已注册设备 |
| `verify` | 验证 HAP 签名 |

## 安装

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

## 架构与原理

```
浏览器授权（agent 工具）        Python 脚本（harmonyos_sign）
┌─────────────────────┐      ┌──────────────────────────────────┐
│ 打开授权 URL         │ ──▶ │ oauth-login: 生成 URL + 等待回调  │
│ 检查登录→点击允许    │      │  tempToken → jwtToken → oauth2Token│
└─────────────────────┘      └──────────────┬───────────────────┘
                                            ▼
                            connect-api.cloud.huawei.com（oauth2Token 认证）
                            cert/add 签发证书 + reapply 下载 .cer
                            device/add 注册设备 + 创建调试 Profile
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
