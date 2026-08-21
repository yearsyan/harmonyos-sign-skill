---
name: harmonyos-signing
description: HarmonyOS 应用签名与真机安装全流程。提供命令行工具链（hdc/ohpm/hvigorw）环境检查、DevEco 客户端 OAuth 登录模拟（获取 oauth2Token）、云端签发证书与调试 Profile、本地 HAP 签名、hdc 安装与启动验证的完整 Python 方法。浏览器授权由 agent 自主完成（用其可用的任意浏览器自动化能力，如 WebBridge/CDP/Playwright/browser-use；未登录则提示用户），脚本只生成授权 URL 并等待回调。当用户需要对 HarmonyOS HAP 签名、安装应用到 HarmonyOS 真机、复刻 DevEco 自动签名、处理证书/Profile/UDID、排查 hdc 连接或签名校验失败时使用。
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

# 2. 登录取 oauth2Token（浏览器授权由 agent 完成，见下节）
python3 -m harmonyos_sign oauth-login       # -> ~/.ohos-oauth/oauth2token.txt

# 3. 一键签名+安装：certId/deviceId 全部可省略（自动签发证书/匹配设备/注册设备）
python3 -m harmonyos_sign online-sign entry-default-unsigned.hap com.example.pkg

#    幂等：p12/证书材料已有则复用（work/cert-id.txt 需通过公钥指纹配对校验），
#    换机器/删 p12/缓存过期 自动处理：指纹不配对 → 清理由本工具签发的旧证书 → 重新签发
#    也可拆步执行：
python3 -m harmonyos_sign new-cert           # 仅确保证书材料（p12+CSR→cert/add→下载.cer）
python3 -m harmonyos_sign certs              # 查云端证书（标记本工具材料 + 公钥指纹）
python3 -m harmonyos_sign cert-delete <id...>  # 删除云端证书（清配额/清理不配对证书）
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

脚本输出授权 URL 后，**由 agent 自主完成浏览器授权**（不是等待用户）。浏览器自动化能力
因 agent 而异（Kimi WebBridge / Chrome DevTools MCP / Playwright / 内置 browser use /
浏览器扩展 CDP 等），**本 skill 不绑定也不要求具体工具**——按目标操作即可，用你当前
环境可用的任意浏览器能力：

1. **导航**：用你的浏览器能力打开授权 URL（新标签页）。
2. **检查页面**：
   - 页面出现「允许」按钮 → 点击它（授权完成，等待脚本收到回调）
   - 页面是登录表单 → 提示用户完成登录（或截图给用户扫码）；登录后页面会回到授权页，
     再点击「允许」
3. 回调到达 → `oauth-login` 自动续兑 oauth2Token，流程结束。
4. 没有浏览器自动化工具时（或全部失败）：若机器上有浏览器（chrome/chromium/firefox/safari 等），
   直接用系统方式打开授权 URL 并提示用户操作——如 `xdg-open <url>`、`google-chrome <url>`、
   `sensible-browser <url>`（Windows 用 `start <url>`，macOS 用 `open <url>`）；
   让用户在弹出的浏览器窗口里登录/点击「允许」。
5. 连浏览器都没有或打不开时，才把 URL 文本交给用户手动打开。
6. 超时（默认 5min）→ 脚本停止并提示；agent 提醒用户检查/重试。

> 环境注意：回调服务器默认监听 `0.0.0.0:18487`（容器/QEMU 端口转发场景转发目标是 guest IP，
> 仅回环监听收不到回调）；输出带 flush，重定向到日志文件也能实时看到进度。

**关键参数**（详见 protocol.md §3-5）：
- 证书签发端点: `POST connect-api.cloud.huawei.com/api/cps/harmony-cert-manage/v1/cert/add`
  body `{csr:<PEM全文>, certName, certType:"1"}` → 响应 `harmonyCert.id/certObjectId`（★ 带 /add，无后缀的 /cert 是 404）
- 证书删除端点: `DELETE /api/cps/harmony-cert-manage/v1/cert/delete` body `{"certIds":[...]}`
  ★ **必须是 DELETE 方法**（POST 会 404）；参数名是 `certIds`（certId/ids 回 invalid parameters）。
  非实名账号证书配额实测 3 张/账号，占满后 cert/add 报错，删旧证书后才能签发新的
- 证书列表端点: `POST /api/cps/harmony-cert-manage/v1/cert/list` 响应含 `publicKeySha256`（公钥配对指纹）
- 文件下载端点: `POST /api/amis/app-manage/v1/objects/url/reapply` body `{"sourceUrls":"<certObjectId|OBS url>"}`
  → `urlsInfo[0].newUrl`（OBS 预签名 300s；证书 .cer 与 Profile 均走此端点，从 DevEco 插件反编译确认）
- Profile 创建端点: `POST /api/cps/provision-manage/v1/ide/test/provision/add`
  `deviceList` 传 **deviceId 字符串**（≤32字符），不是 UDID/对象
- `Accept: */*` 头是 jwtToken 兑换的必要条件
- 云证书 .cer 为三证书链（叶→Huawei CBG Developer Relations CA G2→Root CA G2）
- 本地私钥库（.p12）必须与云证书匹配：工具在复用/缓存证书时会校验
  `SHA256(base64(公钥点))` 指纹（与云端 publicKeySha256 同口径），不配对自动清理重签；
  手动比对可用 `certs`（云端指纹）vs `keytool -exportcert ... | openssl ...` 计算的本地指纹
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
| p12 与云证书不配对 | p12 重生成/换机器/缓存过期 | 新逻辑自动处理：指纹校验 → 清理不配对旧证书 → 重签；手动可 `cert-delete <id>` 后重跑 new-cert |
| 证书删除 404 / invalid parameters | 方法或参数名错误 | ★ `DELETE` 方法 + body `{"certIds":[...]}`（POST 404；certId/ids 报参数错） |
| 证书签发报错（配额） | 非实名账号证书上限（实测 3 张） | 自动清理可删旧证书重试；手动 `certs` 查看后 `cert-delete` 清理 |
| `Accept xxx is not supported` | Accept 头错误 | jwtToken 兑换必须 `Accept: */*` |
| jwtToken 兑换失败 | 缺参数/头 | tempToken+site=CN+version+appid=1007 |
| deviceList 反序列化失败 | 传了对象/UDID | 传 deviceId 字符串(≤32字符) |
| 回调超时 | 回调端口被占/端口转发没到 | 检查 18487 端口；容器/QEMU 转发需回调监听 0.0.0.0（默认已改）；favicon 覆盖旧版已修复 |
| hdc list targets 空 | USB 无权限/未开调试 | 检查 udev 规则（vendor 12d1）+ 设备开发者模式 |

详细协议见 [references/protocol.md](references/protocol.md)。
