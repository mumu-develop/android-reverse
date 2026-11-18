# 小红书 unidbg 离线签名 · 打通记录

> 2026-11-17 凌晨
> 目标：不依赖真机，用 unidbg 仿真 `libxyass.so` 生成服务端接受的 `shield`

---

## 一、结论

**已打通。** 纯本地 unidbg 生成的 `shield` 被服务端接受，实测：

```
GET https://rec.xiaohongshu.com/api/sns/v6/homefeed?oid=homefeed_recommend

HTTP 200
{"code":0,"success":true,"data":[ ... 10 条笔记 ... ]}

单次签名 ~0.28s（热）/ 0.75s（冷）
连续 20 次：20/20 成功，平均 1.16s
并发 5 请求（池=2）：5/5 成功
```

---

## 二、关键突破点

### 1. 拿到 native 注册表（绕过 JNI_OnLoad 混淆）

`libxyass.so` 的 `JNI_OnLoad` 被控制流平坦化，但 unidbg 能跑它。
打开 unidbg 的 DEBUG 日志后，`RegisterNatives` 的完整表直接打印出来：

| 方法 | 签名 | 偏移 |
|---|---|---|
| `intercept` | `(Lokhttp3/Interceptor$Chain;J)Lokhttp3/Response;` | `0x3ad79` |
| `initialize` | `(Ljava/lang/String;)J` | `0x45531` |
| `updateCachedSsk` | `([BLjava/lang/String;)V` | `0x4607d` |
| `getRuntimeDataAccessV1` | `()J` | `0x4714d` |
| `destroy` | `(J)V` | `0x4681d` |
| `X25519KeyExchange.x25519Native` | `([B[B)[B` | `0x25821` |

关键：`JNI_OnLoad` 返回值是 **-1**，unidbg 会抛 `Illegal JNI version`，
但注册已经完成，异常可以忽略；而 `loadLibrary(so, true)` 因为符号解析失败会**静默跳过**，
必须手动 `findSymbolByName("JNI_OnLoad")` + `call`。

### 2. config 与 SSK（真机抓取）

```
[XHS-CONFIG] initialize("main") => 3973144432      ← config 固定是 "main"
[XHS-SSK]    updateCachedSsk(len=22, sid=xnDPBZtu...)  ← SSK 22 字节，按 sid 绑定
```

### 3. 用真实 APK 提供 Java 类 + 假 Chain 调 native

参考 [LitSummer/xhs_unidbg_sign](https://github.com/LitSummer/xhs_unidbg_sign) 的思路：

```java
vm = emulator.createDalvikVM(new File("小红书.apk"));   // 拿到 okhttp3 类
nativeCls = vm.resolveClass("com/xingin/shield/http/Native");
vm.loadLibrary("xyass", true);                          // 加载 libxyass
nativeCls.callStaticJniMethod(emulator, "initializeNative()V");
handle = nativeCls.callStaticJniMethodLong(emulator, "initialize(Ljava/lang/String;)J", "main");

Request req = new Request.Builder().url(url).build();
RealInterceptorChain chain = new RealInterceptorChain(空list, null, null, 0, req, null, 0,0,0);
Response resp = (Response) nativeCls.callStaticJniMethodObject(emulator,
        "intercept(Lokhttp3/Interceptor$Chain;J)Lokhttp3/Response;", chainObj, handle).getValue();
return resp.header("shield");
```

配套的 `AbstractJni` 桩（缺一个就会 `intercept 返回空`）：

- `ContextHolder->sDeviceId` → 我们的 deviceId
- `ContextHolder->sAppId` → `0xecfaaf01`
- `ContextHolder->writeLog(I)V` → 空实现（**最容易漏**）
- `SharedPreferences.get("s","main_hmac")` → 我们的 hmac
- okhttp3：`Request/HttpUrl/Headers/RequestBody/Request$Builder/Interceptor$Chain->proceed`
- okio：`Buffer.writeString/clone/read`

---

## 三、不需要登录（游客态，已实测）

读接口**不要求登录**，但要求 `x-mini-*`：

| 场景 | 结果 |
|---|---|
| 有效设备 + 游客 cp，**无 x-mini** | `200 / code=-100 请登录账号` |
| 有效设备 + 游客 cp + `x-mini-*` | **`200 / code=0 / 10 条`** |
| 10 连发 | **10/10**，平均 1.25s |
| 并发 4 | **4/4**，总 1.3s |
| 同一批 x-mini 换设备 | 主设备 5/5、伪造设备 3/3 ✅ 可跨设备复用 |

`x-mini-*` 来源：Xposed 模块打印的 `[XHS-HDRS]`（一次请求的全部头）。
抓一次写进 `guest_mini.json`，服务热加载即可。
刷新：`Xposed/小红书/xhs_guest_refresh.py`

## 四、最小必需请求头（实测）

```
shield              ← unidbg 生成
xy-platform-info    ← unidbg 生成
xy-common-params    ← 真机会话（含 sid/id_token/gid/did/t）
user-agent
referer
```

**不需要 `x-mini-*` / `xy-tt`** —— 服务端对 homefeed 不校验，省掉了 libtiny 的逆向。

---

## 四、设备身份的边界（重要）

| 尝试 | 结果 |
|---|---|
| 真实 deviceId + 真实 hmac + 真实 common | ✅ HTTP 200 / code 0 / 10 条数据 |
| **真实 deviceId + 真实 common + 随机 hmac** | ❌ HTTP 406 |
| 随机 deviceId + 随机 hmac | ❌ HTTP 406 |
| 随机 hmac 调 `device/regist` | ❌ HTTP 406 |

最后一组是隔离实验：只把 hmac 换成随机值，其余（deviceId / common / UA）全部真实，
依然 406 —— 说明**服务端直接校验 hmac 本身**，不是校验设备指纹。

**`main_hmac` 是服务端按设备下发的密钥**，本地无法凭空生成（它是 shield 的 AES 输入，
服务端必须持有同一把才能验签）。

### 拿到多台设备：ANDROID_ID 指纹伪造（已打通，最快）

**关键发现**：服务端按 **ANDROID_ID** 下发 (deviceId, main_hmac) 密钥对。

用 Xposed 钩 `Settings.Secure.getString("android_id")` 返回伪造值，
再清掉 `s.xml` / `pre_device.xml.xml`，App 就会以为自己是全新设备，
自动向服务端注册出一对新密钥：

```
伪造 AID ad8210c6f197c497
  → deviceId 3efdd6e1-81f3-3013-80a8-d958536e194b
  → hmac     8e4ZikR5VdjsNnx6o4ReNAuK5X18pn8Uy8belEZtigIf19hcNkbHsrleuOE2JBVKq...
  → 服务端接受（HTTP 200，不是 406）
```

工具：`Xposed/小红书/xhs_spoof_device.py`（一轮约 40 秒，自动恢复原身份）

```bash
python xhs_spoof_device.py --serial <序列号> --count 5 --out devices.jsonl
```

实测输出：
```
原设备: 80e5f6b9-a89c-3c25-bbdd-77f1e19bbbec
[1/1] 伪造 ANDROID_ID = caf6111c5615fbba
  ✓ deviceId = 883cd8e1-cda6-3446-aa09-bea77ac3623f
恢复原身份: 80e5f6b9-...
```

### 拿到多台设备：多用户铸造（备用）

`main_hmac` 是按 **ANDROID_ID**（用户+签名隔离）下发的，不是账号绑定。
新建 Android 用户 → 安装小红书 → 首次启动点同意 → App 自己注册出新设备：

```
user 10 → deviceId fc5a28d7-3dbd-3bf5-af44-4713734b9a38
          hmac     X7Jt8EZ0e3YkCPJslELY8/hBBaPA38Ta...
实测：新设备签名 + 真实会话 → HTTP 200 / code=0 / 10 条数据 ✅
```

工具：`Xposed/小红书/xhs_mint_device.py`（`--out devices.jsonl` 存设备池）

> 坑：该机型 `am switch-user` 偶发卡住 system_server，需要 reboot 恢复；
> 铸完要立刻采集（用户停止后 FBE 会锁数据目录）。

### 其他路径

1. **采集真机身份**（当前最实际，工具已提供）
   ```bash
   # 读当前身份
   python Xposed/小红书/xhs_harvest_device.py --serial <序列号> --out devices.jsonl
   # 破坏性：清数据造新身份（游客态即可，但会丢登录）
   python Xposed/小红书/xhs_harvest_device.py --clear --out devices.jsonl
   ```
   - deviceId ← `shared_prefs/pre_device.xml.xml` 的 `device_id`
   - hmac ← `shared_prefs/s.xml` 的 `main_hmac`
   - 一条 (deviceId, hmac) 可长期离线复用，被封再换下一条
2. **逆向 hmac 下发流程**（未完成）
   - 接口已定位：`/api/sns/v2/system_service/device/regist`
   - 需要抓首次启动的注册请求/响应，看 hmac 是否下发
   - 目前用随机 hmac 签该 URL 时本地 `intercept` 会 NPE，待查

---

## 五、工程与用法

```
D:\idea\IdeaProjects\xhs-sign-server\
├── src/main/java/com/xhs/sign/XhsShieldSign.java    unidbg 签名核心
├── src/main/java/com/xhs/server/service/SignPool.java  并发池
├── src/main/java/com/xhs/server/web/XhsController.java 接口
└── README.md
```

接口：

```
GET /xhs/ping                                  存活 + 设备信息
GET /xhs/shield?url=...                        只算 shield
GET /xhs/headers?url=&common=...               签名后的全部头
GET /xhs/request?url=&common=&method=          签名 + 发送
GET /xhs/sign?url=&common=                     走池签名
GET /xhs/testsign?url=&deviceId=&hmac=         指定设备调试
```

演示脚本：

```
D:\PythonProject\安卓-逆向\Xposed\小红书\xhs_unidbg_demo.py

python xhs_unidbg_demo.py --common-file cp.txt doctor
python xhs_unidbg_demo.py --common-file cp.txt fetch --url "https://rec.xiaohongshu.com/api/sns/v6/homefeed?oid=homefeed_recommend"
python xhs_unidbg_demo.py --common-file cp.txt stress --n 20
```

---

## 六、踩坑清单

1. `vm.getJNIEnv()` 在 `loadLibrary` 前返回 0；JNIEnv 在 JNI_OnLoad 时才创建
2. hook JavaVM vtable 的 `GetEnv` 会破坏 unidbg 调用（宿主桩）
3. `loadLibrary(so, true)` 符号解析失败会静默跳过 JNI_OnLoad
4. 缺 `ContextHolder.writeLog` 桩 → `intercept` 返回空
5. 同 JVM 多个 unidbg 实例会偶发 handle 冲突 → 尽量分离进程
6. Gradle 的 `gradle-daemon-jvm.properties` 里 `toolchainVersion=25` 会导致下载 JDK 25 失败 → 删掉


---

## 补充：设备身份的离线推导（2026-11-17 夜）

### 1. deviceId 算法（已验证）

```
step1    = UUID.nameUUIDFromBytes(ANDROID_ID.getBytes())          # md5
deviceId = UUID.nameUUIDFromBytes((step1 + 毫秒时间戳).getBytes())
```

实测：
```
md5("abcdef0123456789")                      → 342645b1-9f3f-31e3-9077-dc1ec0232ac7
md5("342645b1-...-dc1ec0232ac7"+"1794927383073") → dc955dbd-e5b1-3451-b37a-c50d415e7521
```
与 App 生成值逐字符一致（通过 hook `UUID.nameUUIDFromBytes` 抓到入参）。

### 2. hmac 的下发点（已定位）

响应头 **`Xy-Ter-Str`**，128 字符 base64。

- 已注册设备：该值 == `s.xml` 里的 `main_hmac`（逐字符匹配）
- 任意请求都会返回（连 406 都有）
- 命中接口：`device_type`、`user/activate`、`redconfig`、`permission/report`

### 3. 到哪一步了

| 环节 | 状态 |
|---|---|
| deviceId 纯算法生成 | ✅ |
| 从 `Xy-Ter-Str` 拿 hmac | ✅ |
| unidbg 用伪设备签名，服务端接受 | ✅ HTTP 200（数据接口） |
| `/user/activate` 创建游客会话 | ❌ 406（真实设备复刻请求也是 406，待查） |

结论：**设备指纹可以完全离线批量生成**；**会话创建还差一步**。


---

## 最终突破：完全离线造设备 + 造会话（2026-11-17 深夜）

### 1. shield 覆盖的不只是 URL

**关键发现**：`shield` 的签名输入包含 **请求头**，不只是 URL（和 body）。

- 只传 URL + body → `activate` 返回 406
- 传入**完整请求头**（x-legacy-*、xy-direction、x-mini-* 等）→ **200**

前缀也不代表 HTTP 方法（GET/POST 都有两种前缀变体），是别的东西。

### 2. `/api/sns/v1/user/activate` 可以用我们的签名调通

```
POST /api/sns/v1/user/activate
body: android_id=<AID>&did_cur_value=<32hex>&client_public_key_base64=<X25519公钥>&...
签名: unidbg + 完整头
→ HTTP 200
→ 响应: session / secure_session / user_token / userid / ssk
```

实测返回：
```
session   : 1794928226117013318392   → sid = session.1794928226117013318392
user_token: 2afc716765c0aca188579a81ec8ccf48
userid    : 6afacf2d0000000005005c03
ssk       : (X25519 协商结果)
```

### 3. 完整离线链路（已跑通）

```
随机 AID
  → deviceId = uuid3(uuid3(AID) + 毫秒时间戳)        [纯算法]
  → 任意请求 → 响应头 Xy-Ter-Str = hmac              [无需签名]
  → unidbg 签名（URL + body + 完整头）               [离线]
  → POST /user/activate → sid / user_token / ssk     [离线]
  → 带 sid 请求 homefeed → 200                        [仅受每日配额限制]
```

实测最后一步返回 `code=-20240855 访问次数已达上限`（不是 406），说明**签名与会话都被接受**，只是当天配额用尽。

### 4. 仍需注意

- `x-mini-*` 有时效（目前复用抓包值），过期需重新抓
- 每个「设备+会话」每天约 47 次配额
- 未登录账号的游客态同样受配额限制


---

## libtiny（x-mini）逆向进展

### 1. 结构

`libtiny.so` 只导出 `JNI_OnLoad`，通过 `RegisterNatives` 注册 **1 个** native：

```
class : com/xingin/tiny/internal/t
method: a(int, Object[]) -> Object
addr  : base + 0x97a01
```

### 2. 调用约定（真机 hook 确认）

```
t.a(98859282, ["", host, "/"+path, query, null])
  → { x-mini-gid, x-mini-s1, x-mini-sig, x-mini-mua }
```

magic = **98859282**（通过 hook `t.a` 抓返回值里含 x-mini 的那次得到）。

### 3. unidbg 侧现状

- 用**原始小红书 APK** 建 VM（不需要打包 dex）+ `libtiny.so`
- 手动调 `JNI_OnLoad` 后，`nativesMap` 能拿到
  `a(I[Ljava/lang/Object;)Ljava/lang/Object; = base+0x97a01`
- 但调用返回 **null**

### 4. 为什么需要 APK

unidbg 调的是 **JNI 方法**，参数是 Java 对象（jstring/jobjectArray）、返回值是 Java Map。
所以需要 dex 提供「类名 + 方法签名」这些元数据；**代码本身全在 .so 里**。
直接用原始 APK 即可，不需要任何重新打包。

### 5. 下一步

`t.a` 内部依赖 App 上下文（`sjc.f`），需要先走初始化。
做法：hook 启动时**所有** `t.a` 调用，记录 magic 顺序，找到 init 那几个，
在 unidbg 里按序复现（补 Context / PackageInfo 等桩）。


---

## 最终结论：签名与协议已完全正确，卡在「会话过期」（2026-11-18 上午）

### 验证结果

| 验证项 | 结果 |
|---|---|
| 我们的 shield vs App 的 shield | **前 44 字符完全一致**（`XYjf4AB1Vpnoqm16RIlJz5YE0J9NlS1q7ImFmUvmflcoDbfcKh/x`） |
| 22 个请求头 | 全部一致（值逐项比对） |
| `xy-platform-info` | 完全一致 |
| `xy-common-params` 时间戳 | 新鲜（约 60 秒内） |
| unidbg 时间 | `clock_gettime(CLOCK_REALTIME)` = `System.currentTimeMillis()`，真实时间 |
| 设备系统属性对齐（Pixel 6） | **不影响 shield 前缀**（排除） |

### 关键证据

**App 自己的 homefeed 响应也是 `-100 登录已过期`**（hook `RealInterceptorChain` 读取响应体确认）：

```
[XHS-CODE] .../api/sns/v6/homefeed => code=-100 msg=登录已过期 len=53
```

App 界面显示的图文是**本地缓存**（图片、标题都能显示，但请求全失败）。

### 结论

1. **签名链路 100% 正确** —— shield 前缀与 App 逐字符一致，服务端不再返回 406
2. **游客会话已过期** —— 昨日可用的 `session.1794921945772602723284` 过期
3. **新游客会话不能浏览** —— 用 activate 新造的会话请求数据返回 `-100 请登录账号`
4. 因此：**必须登录真实账号** 才能拿到可用会话

### 后续方案

```
登录账号（短信）
  → 拿到有效会话（sid / id_token / ssk）
  → 设备可无限伪造（deviceId 纯算法 + hmac + 签名）
  → 会话 + 新设备 → 采集
```

设备维度可以批量造（已验证），会话维度需要账号。


---

## 【重要更正】免登录采集方案已打通（2026-11-18 晚）

### 之前的结论错了

之前判断「必须登录」是基于**App 接口**（`/api/sns/v6/homefeed`）的 `-100`。
但 **Web 端页面（SSR）不需要登录**，只要用对 TLS 指纹即可。

### 关键：curl_cffi 的 TLS 指纹模拟

小红书会按 **TLS 指纹**区分浏览器和脚本：

```python
from curl_cffi import requests as cr
r = cr.get("https://www.xiaohongshu.com/explore",
           impersonate="chrome",   # ← 关键
           timeout=30, verify=False)
```

用普通 `requests`/`urllib` → 登录墙；用 `impersonate="chrome"` → 正常返回数据。

### 数据在页面的 __INITIAL_STATE__ 里

```
<script>window.__INITIAL_STATE__={...}</script>
```

| 页面 | 路径 | 内容 |
|---|---|---|
| 发现页 `/explore` | `.feed.feeds` | 推荐流：id / xsecToken / 标题 / 作者 / 点赞 / 封面 |
| 笔记页 `/explore/<id>?xsec_token=` | `.note.noteDetailMap` | 详情：正文/图片/标签/互动数/评论 |
| 用户页 `/user/profile/<uid>` | `.user.notes` | 该用户的笔记（**noteId 被置空**，拿不到 id） |

### 实测数据

```
推荐流: 31 条/次，每次全部是新的
  4 次请求 → 114 条不重复笔记
  2 轮批量 + 详情 → 62 条完整笔记（含赞/藏/评/图片/标签）
```

### 限制

- 用户主页的笔记列表**拿不到 noteId**（小红书故意置空），只能拿标题/点赞/封面
- 搜索页 SSR 为空（前端渲染）
- 笔记列表接口 `/api/sns/web/v1/user_posted` 需要 `x-s` 签名，用 xhshow 签名仍 406（a1 未被认可）

### 工具

`Xposed/小红书/xhs_web_scraper.py`

```bash
python xhs_web_scraper.py feed                 # 推荐流 30 条
python xhs_web_scraper.py feed --detail 5      # 前 5 条取详情
python xhs_web_scraper.py note <id> <token>    # 笔记详情
python xhs_web_scraper.py user <user_id>       # 作者笔记列表
python xhs_web_scraper.py batch --pages 5 --out notes.jsonl
```
