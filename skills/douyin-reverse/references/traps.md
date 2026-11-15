# 踩坑实录 · 症状 → 原因 → 处理

按"你看到什么"索引。这些都是实际耗时数小时的坑。

## A. 请求层面

### A1. 服务端返回 `-99999`

**别急着怀疑签名算法。** 90% 是请求参数不全。

| 现象 | 缺什么 |
|---|---|
| `{"has_more":0,"status_code":0,"comments":[],"total":0}` + 尾随 `-99999` | 参数不全 |
| `status_code=-99999` 且无 comments | 同上 |

必备参数（缺一不可）：

```
aid app_name version_code version_name manifest_version_code update_version_code
device_platform device_type device_brand os os_api os_version channel
device_id iid cdid resolution dpi host_abi cpu_support64 language ac
_rticket ts aweme_id cursor count
```

**排查顺序**：
1. 先把真机的完整参数抓下来（见下），全量照抄
2. 确认 `device_id/iid/cdid` 与签名用的**同一套**
3. 最后才怀疑签名

真机完整参数从哪拿：hook `org.json.JSONObject.toString()`，过滤含 `device_id=` 的串
（抖音的 WebSocket 连接串里带全量参数）。

### A2. `Access Denied` / `X-TT-System-Error: 3`

> 参数与上限的完整实测见 `fetch-tuning.md`。

**原因**：短时间请求过多，触发了限流（设备级）。

**恢复**：等 1-3 分钟。实测 45 秒不够，2 分钟仍未必恢复。

### A3. 返回 `status_code:0` 但 `comments:[]`（软封禁）

**原因**：限流的"软"形态，看起来正常但没数据。比 `Access Denied` 更坑。

**判定**：`cursor=0` 也返回空 → 确定被限。

**限流按设备走，不是 IP。** 决定性实测：池内 6 台设备全部冷却（`pauseMs=104s`）时，
一台刚注册的新设备**一次请求就通**。所以"换新设备立刻可用"不是假象，是真的恢复了配额。
但注意：单台设备仍有窗口配额（约 20-40 请求），换设备只是换了一份配额，不是无限。

### A4. 翻页深度到不了 total

**现象**：`total=13013`，但抓到 6000-7000 后再往后全是空页。

**原因**：抖音对单视频的评论可见深度有上限（实测 6000-8000 条），且限流会加剧。

**结论**：13k 评论抓不齐是正常的，能拿到 50-60% 已属正常水平。
实测最好一次 7115/13013（54.7%）。**这是服务端深度上限，不是优化问题**，
详见 `fetch-tuning.md` §一。

### A5. `count` 传 100 只返回 50

**上限就是 50。** 传更大值无效，不会报错。

## B. unidbg 层面

### B1. `frameSign` / `0x2000006` 返回 null，且重试无效

**原因**：初始化失败是**粘性**的。同一 emulator 一旦失败，后续全失败。

**处理**：探针验证 + **重建整个 emulator**（不是重试调用）：

```java
for (int i = 0; i < 15; i++) {
    var s = new Signer(...);      // 全新实例
    s.init();
    if (s.sign(PROBE) != null) break;
}
```

单次成功率约 1/3，重建后必然成功。

### B2. `NullPointerException: UnidbgPointer.toIntPeer() because "pointer" is null`

**原因（两种）**：

1. **跨线程调用** —— emulator 在 A 线程创建，在 B 线程用。
   每个实例绑一条专属线程，构造和签名都提交到该线程。
2. 未知 JNI 回调返回 null 后 native 直接解引用。

### B3. `svc #0x1a0` 直接退出

**原因**：device_id 用了假的/未注册的值，native 判定环境非法直接 `exit()`。

**处理**：`device_id/install_id` 必须是**已注册**的真实值（真机抓的，或自己注册的）。

### B4. 把真机 `.msdata` 喂给 unidbg → VM 崩溃

**原因**：这些状态文件被设备绑定加密，unidbg 解不开，native 走异常分支。

**处理**：**不要提供 msdata**。`IOResolver` 里放行 `.msdata/` 路径返回 null 即可。
没有状态文件反而能正常跑。

### B5. 静态找函数找不到 / xref 为 0

**原因**：字符串通过间接表访问，没有 `adrp+add` 直连。

**已验证的一次例外**：`libsscronet.so` 的 `x-gorgon` 只有一处引用
（`0x30673c: add x1, x1, #0x3ed`），函数 `0x306498`。

**另一个坑**：ADRP 解码时掩码写错会漏扫。正确写法：

```python
if (w & 0x9F000000) == 0x90000000:      # 不能加 0x1F 位掩码
    immlo = (w >> 29) & 3
    immhi = (w >> 5) & 0x7FFFF
    page = ((immhi << 2) | immlo) << 12
```

### B6. 12 个实例预热要 150 秒

**正常**。每个实例约 3-8 秒（含失败重建），串行预热。
要缩短就少开实例，或者接受启动慢。

## C. 设备注册层面

### C1. 注册返回 `device_id: 0`

**原因**：TTEncrypt 的第二个参数传错。

`ttEncrypt([BI)[B` 的 `I` 是**数据长度**，不是 flag。

```java
// ❌ 传 1 → 只加密 1 字节，输出恒 118 字节，服务端静默返回 0
cls.callStaticJniMethodObject(emulator, "ttEncrypt([BI)[B", input, 1);
// ✅
cls.callStaticJniMethodObject(emulator, "ttEncrypt([BI)[B", input, data.length);
```

### C2. `sig_hash` 填错

**症状**：注册**成功**，不报错，但设备可能被风控降权。

**正确值**（40.2.0）：`aea615ab910015038f73c47e45d21466`

**抓法**：

```bash
adb shell su -c "grep -rho 'sig_hash\":\"[0-9a-f]*' /data/data/com.ss.android.ugc.aweme"
```

### C3. `pm clear` 后 device_id 没变

**原因**：device_id 与硬件指纹绑定，清数据不会重置。

**影响**：无法用"清数据"来触发重新注册抓包。

**变通**：直接自己构造注册请求（见 `unidbg-route.md` §6），不需要真机重新注册。

### C4. 机型指纹同质化

**症状**：注册几十台设备，全是同一机型 → 容易被关联。

**处理**：用**自洽的机型画像池**（品牌↔型号↔系统↔分辨率↔DPI↔ROM↔channel 成组），
随机抽整组，不要逐字段随机拼接。

## D. 环境层面

### D1. 抖音报"网络错误"，但其他 App 正常

**不是 `adb reverse` 的问题。** 检查两项：

```bash
adb shell settings get global http_proxy          # 抓包残留 → settings put global http_proxy :0
adb shell dumpsys connectivity | grep DnsAddresses # 240.0.0.1 = Postern 假 DNS
adb shell ping -c 1 -W 3 www.baidu.com             # 解析到 240.0.0.x 即中招
```

**修复**：

```bash
adb shell settings put global http_proxy :0
adb shell su -c 'am force-stop com.tunnelworkshop.postern'
```

Postern 停了但 DNS 没恢复是常见现象，必要时重启手机。

### D2. Frida 连不上

`frida-server` 会自己挂掉。重启：

```bash
adb shell su -c 'pkill -f florida-server'
adb shell su -c 'nohup /data/local/tmp/florida-server-16.5.9 -D >/dev/null 2>&1 &'
adb forward tcp:27042 tcp:27042
```

### D3. Xposed 模块装了不生效

必须 **force-stop 后重新启动**，LSPosed 不热注入：

```bash
adb shell am force-stop com.ss.android.ugc.aweme
adb shell am start -n com.ss.android.ugc.aweme/.splash.SplashActivity
```

### D4. PC 和手机不同网段

`adb reverse tcp:<port> tcp:<port>`，别用 PC 的 IP 直连。

### D5. PowerShell 写中文文件变乱码

PowerShell 5.1 的 `Get-Content -Raw` 按 GBK 读 UTF-8，写回二次转码。

```powershell
[IO.File]::WriteAllText($p, $s, (New-Object Text.UTF8Encoding($false)))
```

Java 源码里也尽量少写中文注释，IDE/终端编码不一致时容易出 `?` 破坏语法。

## E. 抓包层面（基本走不通）

抖音 40.x 的证书绑定**极难绕过**。实测全部失败：

| 尝试 | 结果 |
|---|---|
| 系统 CA + mitmproxy | Google 域名可解，抖音域名 `does not trust the proxy's certificate` |
| TrustMeAlready（LSPosed，已启用+作用域） | ❌ |
| hook `X509_verify_cert` | ❌ |
| hook `SSL_CTX_set_verify=NONE` | ❌ |
| hook `Cronet_CertVerify_DoVerifyV2` 返回 0 | ❌ |
| 替换 `SSL_CTX_set_cert_verify_callback`（spawn 早期注入） | ❌ |

**结论**：不要在这上面耗时间。要拿真实请求头，直接 hook native 里的头表构造函数
或自己仿真算。

## F. 一个反直觉的现象

`0x2000006` 能产出**格式正确的六神头**，但**真机从不调用这个 op**。

真机启动序列里只有：`0x1000003 0x1000001 0x5000001 0x4000001 0x4000002
0x200000e 0x9000001 0xa000003 0xa000001 0x3000003 0x200000d 0x2000004 0x4000004
0x2000002 0x2000003`。

但仿真调 `0x2000006` 产出的头**能通过服务端校验**（实测 `status_code=0`）。
所以：**不要因为"真机不调用它"就放弃这个 op**。
