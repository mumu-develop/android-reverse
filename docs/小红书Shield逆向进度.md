# 小红书 Shield 逆向 · 进度与结论

> 目标：`com.xingin.xhs` 9.54.1（versionCode 9541801，armeabi-v7a）
> 接口：`https://rec.xiaohongshu.com/api/sns/v6/homefeed`

---

## 一、请求参数/请求头的来源（已完全还原）

### 1.1 `xy-common-params`（Java 层，可纯算）

**拼装**：`kfc.a.b()`

```java
for (entry : provider.c(request).entrySet())
    sb.append(key + "=" + URLEncoder.encode(value) + "&");
return trim(sb.toString(), "&");
```

**字段表**：`nud.e`（ApiArgumentsProviderImpl），40 个键，每个绑定一个取值 lambda：

| 类别 | 字段 | 取值来源 |
|---|---|---|
| 设备常量 | `gid` `deviceId` `did` `cpu_abi` `cpu_name` `project_id` `app_id` `channel` `origin_channel` `versionName` `build` `device_model` `device_level` `tz` `lang` `dlang` `mlanguage` `active_ctry` `data_ctry` `holder_ctry` `uis` `teenager` `SUE` `identifier_flag` `overseas_channel` `folder_type` `auto_trans` `fid` | `DeviceInfoContainer`、`lcd.b`、`o1` 等 |
| 会话 | `sid` `id_token` | `IUserService.getIdToken()` 等 |
| 每次请求变 | `t`（时间戳）、`nqe_score`、`launch_id`、`x_trace_page_current` | `h0b.a.b`、`ta2.c`、`jwd.c` |
| 条件 | `preferred_content_language` | 翻译开关开启时追加 |

### 1.2 其他请求头

| 头 | 生成者 | 算法 |
|---|---|---|
| `xy-direction` | `nud.u`（RegionHeadersInterceptor） | `hash = gd.e(magic_num).f(userid, UTF8).b()`<br>`(hash & 0xFFFFFFFF) % 100 + 1`<br>另补 `destination-zone` |
| `xy-scene` | `nud.x` | `point=<jwd.c.f274134e>&fs=<w()>`，URL 编码 |
| `xy-platform-info` | `nud.e` | `platform=android&build=<n>&deviceId=<id>` |
| `x-legacy-did` | `iad.p`（TinyInterceptor） | `r.e()` |
| `x-legacy-fid` | 同上 | `o1.f299548a.e()` |
| `x-legacy-sid` | 同上 | `lcd.b.f294774a.d()` |
| `xy-business-params` `user-agent` `referer` `xy-live-*` | 业务层 | 常量/系统信息 |
| `session.x` `x-mini-sig` `x-mini-mua` `x-b3-traceid` `x-xray-traceid` | **native** | 见下 |

---

## 二、Native 层（两个签名器）

| 签名 | 入口 | 所在 so | 依赖 |
|---|---|---|---|
| **`shield`** | `com.xingin.shield.http.Native.intercept(chain, handle)` | **`libxyass.so`** | **服务端 X25519 下发的 SSK** |
| **`x-mini-mua` / `x-mini-sig` / `x-mini-gid` / `x-mini-s1`** | `com.xingin.tiny.internal.k3.b(op, ...)` → `com.xingin.tiny.internal.t.a(I, Object[])` | **`libtiny.so`（6.5MB）** | 未知 |

### 2.1 shield 的密钥链（关键）

`com.xingin.shield.ssk.AccountSskClient`：

```
createRequest(token)
   → X25519KeyExchange.generateKeyPair()     生成临时密钥对
   → 返回 clientPublicKey，私钥存 PENDING_KEYS

服务端返回 encryptedSsk
   → acceptResponseAndStore(clientPub, encryptedSsk, sid)
   → X25519KeyExchange.decryptSsk(私钥, encryptedSsk)  → 32 字节 SSK
   → Shield.j(sid, ssk)                                存入 native

Native.intercept(chain, handle)  用 SSK 签名
```

**SSK 按 sid 缓存**（`SHIELD_SSK_KEY_SUFFIX = "_sid_ssk_v3"`）。

### 2.2 libxyass.so 结构

| 项 | 值 |
|---|---|
| 架构 | ARM 32-bit |
| `.text` | 0x575b4（358KB） |
| 导出符号 | **只有 `JNI_OnLoad @ 0x26a05`，size 12528** |
| 异常节 | **`.ppp.ttl` 0x8ebc（36KB）**，开头 `f0b503af` = Thumb 代码 |
| crypto 常量 | MD5 T0 ×1、SHA1 H0 ×2；无 AES/SM3 |
| JNI 辅助导入 | 无 `RegisterNatives`/`FindClass`，仅 `time/memcmp/gettimeofday/malloc/memcpy` |

---

## 三、设备上的密钥材料（已提取）

```xml
<!-- /data/data/com.xingin.xhs/shared_prefs/s.xml -->
<string name="main_hmac">HYVaBHS89UKam/lrqZMLAqZjv54C4rBI6/0D1PA9zVy03EA+meHmSdHTCWGnPiXUQEmzDW7DT95kdXcVOaUPBjWkbrHs1EP8/CsWB9U6nkFUz6tWMvFvXw7MFir6vGo5</string>
```

提取命令：

```bash
adb shell "su -c 'cat /data/data/com.xingin.xhs/shared_prefs/s.xml'"
```

device_id：`80e5f6b9-a89c-3c25-bbdd-77f1e19bbbec`

---

## 四、开源实现调研

| 仓库 | 目标 | 状态 |
|---|---|---|
| [RedNote/Xiaohongshu-Shield-Algorithm](https://github.com/RedNote/Xiaohongshu-Shield-Algorithm) | APP `shield` 纯 Python | 验证到 **9.19.2** |
| [ikenxuan/xhshow-ts](https://github.com/ikenxuan/xhshow-ts) | Web `x-s` | 与 APP 无关 |

### shield 三阶段（README）

```
sign_str (path?query)
  → XYAes   device_id 异或 4 魔数 → 白盒 T-Box 密钥扩展 → AES-128-CBC 解密 → 96 字节
  → XYMd5   sign_str + aes 结果 → 自定义 K 表 → 16 字节
  → XYData  KSA + 变种 RC4 + 字节重排 + Base64 → "XY..."
```

魔数：`0xF1892131` `0xFF001123` `0xF1001356` `0xF1234890`

### 实测适配结果

| 阶段 | 结果 |
|---|---|
| `XYAes` | ✅ **跑通**，输出 64 字节 hex 列表 |
| `XYMd5` | ❌ `ValueError: invalid literal for int() with base 16: '0x0/'` |

**原因**：该实现用字符串操作做 hex 宽度对齐（`hex_byte_pad` / `byte2_to_hex4` / `mem_clr`），
强耦合于 9.19.2 的输入长度。URL 长度变化后走到有 bug 的分支。
且版本差 9.19.2 → 9.54.1，T-Box 与 K 表可能已经变化。

**结论：不能直接复用，需按 9.54.1 重新提取常量并修正实现。**

---

## 五、抓包层的实测结论（另一条线）

| 结论 | 数据 |
|---|---|
| 参数 27 个，一个都不能删 | 删任意 → HTTP 406（签名覆盖整个 query） |
| 必需头 11 个 | 8 个签名相关（缺 → 406）+ 3 个身份相关（缺 → `-100 请登录账号`） |
| 可删头 9 个 | `Host` `x-b3-traceid` `x-xray-traceid` `x-legacy-*` `x-mini-gid/s1/sig` |
| **必须用原始 URL 字节** | 用 `params=` 重新编码 → 406 |
| 有效期约 10 分钟 | 超过 → `-100 登录已过期` |
| **有每日配额** | 约 50 次后 → `-20240855 访问次数已达上限，请改天再试` |

---

## 六、下一步可选项

| 方案 | 做法 | 工时 | 前置 |
|---|---|---|---|
| **A. 修正纯算** | IDA 打开 `libxyass.so`，提 `JNI_OnLoad` 的 RegisterNatives 表 → 找 shield 函数 → 重新提取 T-Box / K 表 → 修正 `XYMd5` | 1-2 天 | 需 IDA |
| **B. Xposed 复用** | hook `Native.intercept`，或在进程内直接发请求，走 Sekiro 暴露给 Python（同抖音架构） | 约半天 | 无 |
| **C. 降级验证** | 不填 HMAC，看默认 `xor_byte` 向量是否被服务端接受 | 10 分钟 | 配额恢复 |

**建议**：先 B 拿到可用数据；A 作为长期方案（离线、可批量）。

---

## 七、文件位置

| 文件 | 说明 |
|---|---|
| `frida-hook/frida-dex/学习/小红书/so/libxyass.so` | 已从 APK 提取，供 IDA |
| `work/xhs_shield/shield_sdk.py` | 开源实现（含 loguru 桩） |
| `work/xhs_shield/test_shield.py` | 抓包对比脚本 |
| `work/xhs_shield/test_fix.py` | 容错补丁版（AES 通过，MD5 待修） |
| `work/xhs/min_params.json` | 抓包原始头/参数 |
