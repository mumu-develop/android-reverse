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

## 三、最小必需请求头（实测）

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

### 拿到多台设备：多用户铸造（已验证）

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
