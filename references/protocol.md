# HarmonyOS 在线签名协议笔记

> 内容来源：官方文档研读、SDK 组件分析、接口实测验证（2026-08 实弹验证于 HarmonyOS 真机）

## 1. 信任体系
- 三级链: 根CA <- 中间CA(Application CA) <- 应用证书(开发者)；Profile 由独立 Profile CA 签发
- HarmonyOS 真机预置华为 CBG 私有根 CA（Root CA G2 -> Developer Relations CA G2 -> 应用证书）
- 设备端校验: 证书链命中预置根 + Profile CMS 签名 + bundleName/证书指纹一致 + 设备ID匹配 + 有效期

## 2. 自动签名时序
```
OAuth登录(DevEco客户端 appid=1007) → 查团队(user.team) → 本地生成密钥/CSR →
上传CSR(add.cert, {csr,certName,certType:1}) → 查证书(get.cert) → 下载.cer →
注册设备(add.device, {deviceName,udid,deviceType}) → 创建调试Profile(signIdeTestProvision) →
本地 sign-app → hvigor 构建 → hdc install
```

## 3. API 端点（中国区，已实弹验证）
### 3a. 云端管理（DevEco 客户端通道，需 oauth2Token）★ 唯一可创建 Profile 的通道
基准: `https://connect-api.cloud.huawei.com/api`
```
POST /cps/provision-manage/v1/ide/test/provision/add   创建调试Profile ★
POST /cps/harmony-cert-manage/v1/cert/list             查证书
POST /cps/harmony-cert-manage/v1/cert                  上传CSR签证书 ({csr,certName,certType:"1"})
GET  /cps/device-manage/v1/device/list?encodeFlag=0&start=1&pageSize=100   查设备 (返回 list)
POST /cps/device-manage/v1/device                      注册设备
POST /ups/user-permission-service/v1/user-team-list    查团队
```
认证头: `oauth2Token: <accessToken>` + `uid` + `teamId`（uid/teamId=账号userId）
其他分区: europeanZoneId -> agc-dre / singaporeZoneId -> agc-dra / russiaZoneID -> agc-drru

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
注: provision **创建**在网页通道被 gate(403)，必须走 3a 的 oauth2Token 通道

### 3c. 文件下载（OBS 预签名 URL，300s 有效）
```
证书: 页面可用 AGC_API.API_CFS.generateFileDownlodUrl({}, {params:{objectId: certObjectId}})
      -> {urlInfo:{url, sha256, fileSize}}；.cer 为三证书链
Profile: 创建响应直接返回 provisionFileUrl (OBS 预签名)
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
# 2. 查询 certId / deviceId
python3 -m harmonyos_sign certs
python3 -m harmonyos_sign devices
# 3. 创建调试 Profile（★ deviceList 传 deviceId 字符串，非 UDID/对象）
POST /api/cps/provision-manage/v1/ide/test/provision/add
  {"certList":["<certId>"],"packageName":"<bundle>",
   "deviceList":["<deviceId>"],"provisionName":"<name>","aclPermissionList":[]}
  -> {provisionFileUrl}  (OBS 预签名, 300s 有效)
# 4. 下载 .p7b；证书 .cer 经 CFS 下载（3 证书链：叶+DeveloperRelationsCA+RootCA）
# 5. 本地签名
java -jar hap-sign-tool.jar sign-app -mode localSign \
  -keyAlias <local-key> -keyPwd 123456 \
  -appCertFile cloud.cer -profileFile profile.p7b \
  -inFile app-unsigned.hap -signAlg SHA384withECDSA \
  -keystoreFile local.p12 -keystorePwd 123456 \
  -outFile app-signed.hap -signCode 1
# 6. 验证 + 安装
python3 -m harmonyos_sign verify app-signed.hap
hdc install -r app-signed.hap ; hdc shell aa start -a EntryAbility -b <bundle>
```

## 6. 实测结果（2026-08-21, API24, 未实名账号）
- OAuth 全流程（tempToken→jwtToken→oauth2Token）✓
- 证书 auto_debug_<userId>.cer（华为 CBG 链）云端签发 ✓
- 调试 Profile p7b 创建 ✓（ide/test/provision/add, deviceList=deviceId）
- HAP 签名 Verify success ✓
- hdc install bundle successfully ✓ + aa start 启动成功 ✓

## 7. 排障速查
| 症状 | 原因 | 处理 |
|------|------|------|
| connect-api 401 | token 无效/过期 | 重跑 oauth-login（token 约 1h 有效） |
| provision 403 (网页通道) | 网页 CSRF 认证被 gate | 必须用 oauth2Token 通道(3a) |
| deviceList 反序列化失败 | 传了对象/UDID | 传 deviceId 字符串(≤32字符) |
| Accept not supported | Accept 头不对 | 必须 `Accept: */*` |
| jwtToken 兑换失败 | 缺参数/头 | tempToken+site=CN+version+appid=1007 |
| 回调超时 | 端口占用 / favicon 覆盖 tempToken | 端口空闲 + 新版 handler 已修复 |