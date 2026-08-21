---
name: harmonyos-signing
description: HarmonyOS 应用签名与真机安装全流程。提供命令行工具链（hdc/ohpm/hvigorw）环境检查、DevEco 客户端 OAuth 登录模拟（获取 oauth2Token）、云端签发证书与调试 Profile、本地 HAP 签名、hdc 安装与启动验证的完整 Python 方法。浏览器授权由 agent 自主选择工具完成（WebBridge/Chrome DevTools MCP/Playwright 等；未登录则提示用户），脚本只生成授权 URL 并等待回调。当用户需要对 HarmonyOS HAP 签名、安装应用到 HarmonyOS 真机、复刻 DevEco 自动签名、处理证书/Profile/UDID、排查 hdc 连接或签名校验失败时使用。
license: MIT
metadata:
  harmonyos: "6.0.1+ (API 21-24)"
  requires: bash, java, python3.9+, keytool, hap-sign-tool.jar
---

# HarmonyOS Signing & Dev Environment

在无 DevEco（Linux 无官方版）环境下完成 HarmonyOS 开发、在线自动签名与真机安装的一站式方法论（Python 实现，零第三方依赖）。

## 架构背景（必读）

> 命名说明：HarmonyOS 5.0 起官方统一称 **HarmonyOS**（早期版本曾称 HarmonyOS NEXT），下文均用 HarmonyOS。

- **信任链**: HarmonyOS 真机预置华为 CBG 私有 CA。签名 HAP 的证书链根必须命中设备预置信任根，否则安装被拒。
- **签名途径**: 模拟 DevEco 客户端 OAuth 登录（appid=1007）→ 云端签发证书/Profile（connect-api）→ 本地 hap-sign-tool 签名 → hdc 安装。**无需 Windows/Mac DevEco，未实名账号也可用**
- **关键事实**: DevEco 官方无 Linux 版（仅 Command Line Tools）；在线签名协议细节见 [references/protocol.md](references/protocol.md)

## 环境布局与工具链自动发现

hdc / ohpm / hvigor / hap-sign-tool.jar 按以下顺序**自动发现**（无需配置）：

```
1. 环境变量: HOS=<command-line-tools根> 或 DEVECO_SDK_HOME / HOS_SDK_HOME / OHOS_SDK_HOME=<sdk根>
2. PATH 中已有的 hdc（which hdc）
3. 各平台 DevEco Studio / Command Line Tools 常见目录（关键词扫描，浅层递归）：
   - Linux:   ~/deveco* ~/harmonyos* ~/ohos* /opt/* /usr/local/*
   - macOS:   ~/Library/OpenHarmony（DevEco SDK 默认目录）
              /Applications/DevEco-Studio.app/Contents/sdk/...  ~/Applications/*
   - Windows: C:\Program Files\Huawei\DevEco Studio\sdk\...  %LOCALAPPDATA%\Huawei\...
4. 支持布局（hdc 定位后自动推导 hap-sign-tool.jar）:
   - Command Line Tools: <root>/sdk/default/openharmony/toolchains/hdc
   - DEVECO_SDK_HOME:    <sdk>/default/openharmony/toolchains/hdc
   - 旧版 SDK:           <sdk>/openharmony/toolchains/hdc
   - macOS DevEco SDK:   ~/Library/OpenHarmony/Sdk/<版本>/toolchains/hdc
                         ~/Library/OpenHarmony/Sdk/<版本>/openharmony/toolchains/hdc
   - macOS .app:         <DevEco-Studio.app>/Contents/sdk/default/openharmony/toolchains/hdc
```

`check-env` 会打印实际发现路径。工作区：`~/.ohos-oauth/`（oauth2token.txt / uid.txt / work/：
online-app.p12 / online-app.csr / cloud.cer / cert-id.txt / profile.p7b）

## 工作流 A：环境检查

```bash
source /home/user/harmonyos/env.sh          # 设置 PATH（hdc/ohpm/hvigorw/工具链）
python3 -m harmonyos_sign check-env          # 检查 hdc/ohpm/hvigorw/SDK/udev
python3 -m harmonyos_sign fetch-udid         # 读取已连接真机 UDID
```

## 工作流 B：在线自动签名 + 真机安装（HarmonyOS）

```bash
# 1. 构建 unsigned HAP
hvigorw assembleHap --mode module -p product=default -p buildMode=debug --no-daemon

# 2. 登录取 oauth2Token（自动探测浏览器后端；未登录会提示用户完成登录）
python3 -m harmonyos_sign oauth-login       # -> ~/.ohos-oauth/oauth2token.txt

# 3. 一键签名+安装：certId/deviceId 全部可省略（自动签发证书/匹配设备/注册设备）
python3 -m harmonyos_sign online-sign entry-default-unsigned.hap com.example.pkg

#    幂等：p12/证书材料已有则复用（work/cert-id.txt），换机器/删 p12 后自动重签
#    也可拆步执行：
python3 -m harmonyos_sign new-cert           # 仅确保证书材料（p12+CSR→cert/add→下载.cer）
python3 -m harmonyos_sign certs              # 查云端证书（标记本工具材料）
python3 -m harmonyos_sign devices            # 查云端已注册设备

# 4. 启动验证
python3 -m harmonyos_sign verify <signed.hap>
hdc shell aa start -a EntryAbility -b <bundleName>
```

### 浏览器授权（agent 协作模式，脚本不依赖任何浏览器工具）

`oauth-login` **只生成授权 URL + 等待回调**，不做浏览器操作：

```bash
python3 -m harmonyos_sign oauth-login --timeout 300   # 生成 URL，等待回调（默认 5min）
```

脚本输出授权 URL 后，**由 agent 自主选择浏览器自动化工具**完成授权：

1. 探测可用工具（Kimi WebBridge / Chrome DevTools MCP / playwright CLI 等）
2. 用工具打开授权 URL → 检查页面状态：
   - 含「允许」按钮 → 已登录，点击「允许」
   - 登录表单 → **提示用户完成登录**，登录后再点击「允许」
3. 回调到达 → 脚本自动继续兑换 oauth2Token
4. 超时（默认 5min）→ 脚本停止并提示；agent 提醒用户检查/重试

**关键参数**（详见 protocol.md §3-5）：
- 证书签发端点: `POST connect-api.cloud.huawei.com/api/cps/harmony-cert-manage/v1/cert/add`
  body `{csr:<PEM全文>, certName, certType:"1"}` → 响应 `harmonyCert.id/certObjectId`（★ 带 /add，无后缀的 /cert 是 404）
- 文件下载端点: `POST /api/amis/app-manage/v1/objects/url/reapply` body `{"sourceUrls":"<certObjectId|OBS url>"}`
  → `urlsInfo[0].newUrl`（OBS 预签名 300s；证书 .cer 与 Profile 均走此端点，从 DevEco 插件反编译确认）
- Profile 创建端点: `POST /api/cps/provision-manage/v1/ide/test/provision/add`
  `deviceList` 传 **deviceId 字符串**（≤32字符），不是 UDID/对象
- `Accept: */*` 头是 jwtToken 兑换的必要条件
- 云证书 .cer 为三证书链（叶→Huawei CBG Developer Relations CA G2→Root CA G2）
- 本地私钥库（.p12）必须与云证书匹配（密钥对在签发证书前生成；换 p12 必须重签证书）
- hap-sign-tool 坑：`-keySize` 写全 `NIST-P-384`（非 N384）；`-subject` 逗号分隔 `"CN=xx, O=xx"`
- 未实名账号可用；非实名账号 AGC 网页控制台会被 302 到实名页，全流程走 oauth2Token 通道

## 安装为命令（可选，避免污染全局环境）

```bash
# 方式1（推荐，零安装）：直接在仓库目录运行
cd harmonyos-sign-skill && python3 -m harmonyos_sign <cmd>

# 方式2（虚拟环境，隔离）
cd harmonyos-sign-skill && python3 -m venv .venv \
  && .venv/bin/pip install -e . \
  && .venv/bin/harmonyos-sign <cmd>

# 方式3（用户级安装，不进系统 site-packages）
cd harmonyos-sign-skill && pip install -e . --user
```
> 不建议裸 `pip install -e .`（会写入当前 Python 环境的全局 site-packages）。

## 故障排查速查

| 症状 | 原因 | 处理 |
|------|------|------|
| connect-api 401 | token 无效/过期 | 重跑 oauth-login（token 约 1h 有效） |
| provision 403（网页通道） | 网页 CSRF 认证被 gate | 必须用 oauth2Token 通道（connect-api） |
| provision "cert not exist" | certId 不存在/抄错 | `certs` 核对 id（19 位数字） |
| `/cert` 404 空响应 | 端点错误 | 签证书用 `/cert/add` |
| 证书下载 404 | 端点错误 | 用 `/amis/.../objects/url/reapply`，sourceUrls=certObjectId |
| code=110 参数错误 | keySize 格式 | ECC 写 `NIST-P-384`；勿传不存在参数 |
| code=101 subject 错 | 分隔符错误 | 逗号+空格 `"CN=xx, O=xx, OU=xx"` |
| p12 与云证书不配对 | p12 重生成/换机器 | 删 work/cert-id.txt 重跑 new-cert |
| `Accept xxx is not supported` | Accept 头错误 | jwtToken 兑换必须 `Accept: */*` |
| jwtToken 兑换失败 | 缺参数/头 | tempToken+site=CN+version+appid=1007 |
| deviceList 反序列化失败 | 传了对象/UDID | 传 deviceId 字符串(≤32字符) |
| 回调超时 | 回调端口被占/favicon 覆盖 | 检查 18487 端口空闲；新版已修复 favicon 覆盖 |
| hdc list targets 空 | USB 无权限/未开调试 | 检查 udev 规则（vendor 12d1）+ 设备开发者模式 |

详细协议见 [references/protocol.md](references/protocol.md)。
