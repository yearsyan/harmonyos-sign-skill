# HarmonyOS 在线签名协议笔记

> 内容来源：官方文档研读、SDK 组件分析、接口实测验证（2026-08 实弹验证于 HarmonyOS 真机）
> 2026-08-21 补充：证书签发/下载端点实测修正（macOS + DevEco Studio 6.0 工具链，未实名账号）

## 1. 信任体系
- 三级链: 根CA <- 中间CA(Application CA) <- 应用证书(开发者)；Profile 由独立 Profile CA 签发
- HarmonyOS 真机预置华为 CBG 私有根 CA（Root CA G2 -> Developer Relations CA G2 -> 应用证书）
- 设备端校验: 证书链命中预置根 + Profile CMS 签名 + bundleName/证书指纹一致 + 设备ID匹配 + 有效期

## 2. 自动签名时序
```
OAuth登录(DevEco客户端 appid=1007) → 查团队(user.team) → 本地生成密钥/CSR →
上传CSR(cert/add, {csr,certName,certType:"1"}) → 查证书(cert/list) →
reapply换取OBS预签名URL → 下载.cer(三证书链) →
注册设备(device/add, {deviceName,udid,deviceType}) → 创建调试Profile(ide/test/provision/add) →
本地 sign-app → hvigor 构建 → hdc install
```

## 3. API 端点（中国区，已实弹验证）
### 3a. 云端管理（DevEco 客户端通道，需 oauth2Token）★ 唯一可创建 Profile 的通道
基准: `https://connect-api.cloud.huawei.com/api`
```
POST /cps/provision-manage/v1/ide/test/provision/add   创建调试Profile ★
POST /cps/harmony-cert-manage/v1/cert/add              上传CSR签证书 ★ ({csr,certName,certType:"1"})
POST /cps/harmony-cert-manage/v1/cert/list             查证书（含 publicKeySha256 配对指纹）
DELETE /cps/harmony-cert-manage/v1/cert/delete ★ 删证书
                                                       ★ 方法必须是 DELETE（POST 会 404）
                                                       ★ body 参数名 certIds: {"certIds":["<id>"]}
                                                       （certId/ids/idList 均回 invalid parameters）
GET  /cps/device-manage/v1/device/list?encodeFlag=0&start=1&pageSize=100   查设备 (返回 list)
POST /cps/device-manage/v1/device/add                  注册设备 ({deviceName,udid,deviceType})
POST /cps/provision-manage/v1/provision/list           查Profile（IDE通道）
POST /ups/user-permission-service/v1/user-team-list    查团队
POST /amis/app-manage/v1/objects/url/reapply           ★ 换取OBS预签名下载URL
                                                       body={"sourceUrls":"<certObjectId|OBS url>"}
                                                       -> {urlsInfo:[{sourceUrl,newUrl,sha256}]} 300s有效
```
认证头: `oauth2Token: <accessToken>` + `uid` + `teamId`（uid/teamId=账号userId）
其他分区: europeanZoneId -> agc-dre / singaporeZoneId -> agc-dra / russiaZoneID -> agc-drru

⚠️ 端点易错点（2026-08-21 实测）：
- 签证书是 `/cert/add`，**不是** `/cert`（后者 404 且响应体为空）
- 删证书是 `/cert/delete` + **DELETE 方法**（POST 会 404）；参数名必须是 `certIds` 数组
  （certId/ids/idList 回 `[AppGalleryConnectProvisionService]invalid parameters`）；
  证书列表响应 `allowDel` 字段标记允许删除（本工具签发的 cli_debug_* 证书为 1）
- 非实名账号证书配额：实测 **3 张/账号**，占满后 cert/add 报配额错误；
  需先删旧证书（cert-delete 命令或本工具自动清理）再签发
- 证书配对指纹：cert/list 响应 `publicKeySha256`（冒号分隔 hex）与本地 p12 公钥
  同口径 = SHA256(base64(SPKI 中 BIT STRING 裸公钥点)) 的小写 hex；
  工具会用它自动校验/匹配/清理，避免换机器后签名报 keyAlias 不配对
- 证书/Profile 文件下载不在 cert-manage 域内，走 `/amis/app-manage/v1/objects/url/reapply`；
  把 `certObjectId`（cert/list 返回）或 OBS `provisionFileUrl`（provision/add 返回）作为
  `sourceUrls` 传入即可换预签名 URL（此端点从 DevEco Studio 的 hos-project-mgmt 插件
  `SignatureMgmt.properties` 反编译确认，oauth2Token 通道实测可用）
- 非实名账号访问 AGC 网页控制台（developer.huawei.com/console*）会被 302 到实名认证页，
  网页通道（3b）整体不可用——全部走 oauth2Token 通道即可

### 3b. 网页控制台通道（已登录 AGC 页面，X-HD-CSRF 认证）
基准: `https://agc-drcn.developer.huawei.com/agc/edge`
```
/ups/user-permission-service/v1/user-team-list   查团队
/cps/harmony-cert-manage/v1/cert/list            查证书（certObjectId 用于下载）
/cps/device-manage/v1/device/list                查设备 (返回 deviceInfos)
/cps/provision-manage/v1/provision/list          查Profile（创建被 gate 403）
```
认证头: `X-HD-DATE`(YYYYMMDDTHHMMSSZ) + `X-HD-CSRF`(cookie csrftoken) + `agcTeamId`
页面封装: `window.AGC_API` 对象（API_CPS/API_UPS/...），wo 客户端自动附加认证头
注: provision **创建**在网页通道被 gate(403)，必须走 3a 的 oauth2Token 通道；
非实名账号连 AGC 控制台页面本身都进不去（302 到实名页），故此通道仅对已实名账号有参考价值

### 3c. 文件下载（OBS 预签名 URL，300s 有效）
```
统一入口（oauth2Token 通道，推荐）: POST /api/amis/app-manage/v1/objects/url/reapply
  {"sourceUrls": "<certObjectId 或 provisionFileUrl>"} -> {urlsInfo:[{sourceUrl,newUrl,sha256}]}
网页通道备选: AGC_API.API_CFS.generateFileDownlodUrl({}, {params:{objectId: certObjectId}})
  -> {urlInfo:{url, sha256, fileSize}}
.cer 为三证书链: 叶证书(与本地p12配对) + Developer Relations CA G2 + Root CA G2
Profile: provision/add 创建响应直接返回 provisionFileUrl（OBS 预签名，已可直接下载；
  过期后同样可作为 sourceUrls 传入 reapply 换新）
```

## 4. DevEco 客户端 OAuth 登录（appid=1007）— 已完整复刻
```
① 打开授权页: https://cn.devecostudio.huawei.com/console/DevEcoIDE/apply
   ?port=<本地端口>&appid=1007&code=<随机UUID>
② 用户浏览器登录后点击「允许」→ 服务器 302 → 浏览器 POST 回调到 http://localhost:<port>/callback
   body: tempToken=<512hex>&siteId=1&code=<UUID>
③ tempToken -> jwtToken:
   GET https://cn.devecostudio.huawei.com/authrouter/auth/api/temptoken/check
      ?tempToken=<...>&site=CN&version=6.1.1.300&appid=1007
   头: UA=Chrome/49.0.2623.75, Accept: */* (必须!), Accept-Encoding: identity
   → 响应 = JWT(jwtToken)，payload 含 access_token
④ jwtToken -> accessToken:
   GET https://cn.devecostudio.huawei.com/authrouter/auth/api/jwToken/check
   头: jwtToken=<JWT>, refresh=false, Accept: */*
   → {status:true, userInfo:{accessToken, refreshToken, userId, nationalCode, realName}}
⑤ accessToken 即 oauth2Token，供 3a 使用（有效期约 1 小时，重跑 oauth-login 刷新）
```
脚本: `python3 -m harmonyos_sign oauth-login`（内嵌回调服务器，双监听 127.0.0.1+::1）
脚本**只生成授权 URL + 等待回调**；浏览器操作由 agent 自主选择工具完成
（Kimi WebBridge / Chrome DevTools MCP / playwright CLI 等），
打开 URL → 检查登录（「允许」按钮=已登录，登录表单=提示用户）→ 点击允许；
回调到达后脚本自动继续兑换；默认 5min 超时则停止并提示用户。
注意: 未实名账号同样可用（实测 realName=false 成功安装）✓
回调注意: 服务器对 favicon.ico 等 GET 请求不得覆盖已收到的 tempToken（已修复）

## 5. 在线自动签名调用序列（python3 -m harmonyos_sign）
```bash
# 1. 登录取 token
python3 -m harmonyos_sign oauth-login          # -> ~/.ohos-oauth/oauth2token.txt
# 2.（可选）预先确保证书材料；缺省时 online-sign 也会自动做
python3 -m harmonyos_sign new-cert             # p12+CSR → cert/add → reapply下载.cer → cert-id.txt
# 3. 签名+安装（certId/deviceId 可自动）
python3 -m harmonyos_sign online-sign app-unsigned.hap com.example.pkg
#    自动流程: 证书(复用/签发) → 设备(UDID匹配/注册) → Profile → 本地签名 → hdc install

# 关键请求体:
#   cert/add:        {"csr": <PEM全文>, "certName": "cli_debug_<uid>.cer", "certType": "1"}
#   reapply:         {"sourceUrls": "<certObjectId>"}  -> urlsInfo[0].newUrl 下载 .cer
#   device/add:      {"deviceName": "cli_<udid前8>", "udid": <64hex>, "deviceType": "phone"}
#   provision/add:   {"certList":["<certId>"],"packageName":"<bundle>",
#                     "deviceList":["<deviceId>"],"provisionName":"<name>","aclPermissionList":[]}
#                    （★ deviceList 传 deviceId 字符串，非 UDID/对象）-> {provisionFileUrl}
# 4. 本地签名
java -jar hap-sign-tool.jar sign-app -mode localSign \
  -keyAlias online-app -keyPwd 123456 \
  -appCertFile cloud.cer -profileFile profile.p7b \
  -inFile app-unsigned.hap -signAlg SHA384withECDSA \
  -keystoreFile online-app.p12 -keystorePwd 123456 \
  -outFile app-signed.hap -signCode 1
# 5. 验证 + 安装
python3 -m harmonyos_sign verify app-signed.hap
hdc install -r app-signed.hap ; hdc shell aa start -a EntryAbility -b <bundle>
```

### 5b. hap-sign-tool 参数易错点（实测，2026-08-21）
```
generate-keypair:
  -keySize 必须写全 NIST-P-256/NIST-P-384（写 N384/P384 报 code=110 COMMAND_PARAM_ERROR）
  无 -keyUsage/-keyValidity 参数（传入同样报 code=110）
generate-csr:
  -subject 必须逗号分隔 "CN=xx, O=xx, OU=xx"（斜杠分隔 "CN=xx/O=xx" 报 code=101 格式错误）
```

## 6. 排障速查
| 症状 | 原因 | 处理 |
|------|------|------|
| connect-api 401 | token 无效/过期 | 重跑 oauth-login（token 约 1h 有效） |
| `/cert` 404（空响应体） | 端点错误 | 签证书必须用 `/cert/add` |
| `cert/delete` 404 | 用了 POST | ★ 必须 **DELETE** 方法 |
| `cert/delete` invalid parameters | 参数名错 | body 必须是 `{"certIds":[...]}`（certId/ids 均报错） |
| 证书配额满（签发报错） | 非实名上限 3 张 | `cert-delete` 删旧证书（工具自动清理不配对旧证书后可重签） |
| provision 403 (网页通道) | 网页 CSRF 认证被 gate | 必须用 oauth2Token 通道(3a) |
| provision "cert not exist" | certId 不存在/不属于该账号 | 用 `certs` 命令核对 id（19位数字，勿手抄错位） |
| 证书下载 404 | 走了错误端点 | 用 `/amis/app-manage/v1/objects/url/reapply`，sourceUrls=certObjectId |
| AGC 网页 302 到实名页 | 未实名账号网页通道被 gate | 全流程走 oauth2Token 通道（脚本默认） |
| code=110 COMMAND_PARAM_ERROR | keySize 等参数格式错 | ECC 写 NIST-P-384；不要传不存在的参数 |
| code=101 subject 格式错误 | subject 分隔符错 | 必须逗号+空格: "CN=xx, O=xx, OU=xx" |
| deviceList 反序列化失败 | 传了对象/UDID | 传 deviceId 字符串(≤32字符) |
| Accept not supported | Accept 头不对 | 必须 `Accept: */*` |
| jwtToken 兑换失败 | 缺参数/头 | tempToken+site=CN+version+appid=1007 |
| 回调超时 | 端口占用 / favicon 覆盖 tempToken | 端口空闲 + 新版 handler 已修复 |
