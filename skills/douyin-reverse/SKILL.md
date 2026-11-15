---
name: douyin-reverse
description: 在逆向抖音/TikTok（com.ss.android.ugc.aweme）时使用 —— 还原六神签名头（X-Argus/X-Gorgon/X-Helios/X-Khronos/X-Ladon/X-Medusa）、搭建 unidbg 签名器、离线注册设备，或搭建 Xposed+RPC 中继。两条路线端到端，含已验证的偏移、op 码、配置值、抓取上限与耗时的坑。抖音及其它内置 libmetasec_ml.so 的字节系应用应触发。不适用场景：通用 Android 逆向（转 apk-reverse）、iOS、以及没有 metasec 系签名器的应用。
---

# 抖音逆向 · 主入口

针对 `com.ss.android.ugc.aweme` 的两条已验证路线。**先选路线，再读对应参考文档，不要预读。**

## 路由表

| 你的目标 | 走哪条 | 读哪份 |
|---|---|---|
| 要**脱离手机**、批量签名、做设备池 | **unidbg** | `references/unidbg-route.md` |
| 只求**快速拿到数据**、有 root 手机、能装 Xposed | **Xposed + RPC** | `references/xposed-rpc-route.md` |
| 需要查 op 码 / 配置 JSON / 头字段 / 注册字段 | — | `references/sixgod-contract.md` |
| 卡住了：签名失败、`-99999`、初始化随机失败 | — | `references/traps.md` |
| **抓取慢 / 抓不齐 / 被限流** | — | `references/fetch-tuning.md` |
| **换版本**（40.x → 41.x 等） | — | `references/version-adaptation.md` |
| 要一份能跑的骨架 | — | `assets/minimal-harness/` |
| 要验证"现在到底通没通" | — | `scripts/dy-selfcheck.py` |
| **要交付代码**（任何形态） | — | `references/delivery-principles.md` |

```
read <skill>/references/unidbg-route.md
read <skill>/references/xposed-rpc-route.md
read <skill>/references/sixgod-contract.md
read <skill>/references/traps.md
read <skill>/references/fetch-tuning.md           # 抓取参数与上限
read <skill>/references/delivery-principles.md    # 交付前必读：最小可执行
read <skill>/references/version-adaptation.md      # 换版本时必读
```

### 现成可用的东西

```
assets/minimal-harness/           # 可直接 mvn package 跑的最小工程
  pom.xml
  src/main/java/com/dy/sign/DouyinMetasecSign.java
  README.md                          # 含"换版本要改哪 6 处"

scripts/dy-selfcheck.py              # 自检：health / sign / request / register
  python dy-selfcheck.py --service http://127.0.0.1:8099 --with-register
  python dy-selfcheck.py --java-project <工程目录> --device-id .. --install-id ..
```

## 0. 先判断走哪条（30 秒）—— 但必须让用户拍板

> **闸门前置**：抖音的六神签名已确认属"纯算不可行"（VMP + JIT + 跨库组装）。
> 但**仍然要把难度和工时摆给用户**，由用户选 unidbg 还是 RPC。
> 评估模板与确认纪律见 `apk-reverse` 的 SKILL.md §2。

## 0. 先判断走哪条（30 秒）

| 条件 | 结论 |
|---|---|
| 有 root 手机 + 已装 LSPosed | 两条都能走；**要批量/长期 → unidbg** |
| 没有手机 / 不能装机 | **只能 unidbg** |
| 只要几百条数据、当天要 | **Xposed + RPC**（2 小时能跑通） |
| 要几万条、要并发、要设备池 | **unidbg**（RPC 是单机单进程，扛不住） |
| 目标版本 ≥ 40.x | 两条都验证过；**签名算法在 so 里，没有纯算法移植价值** |

**关键认知 1**：40.x 的六神签名**不能纯 Python 重写**。签名逻辑在 `libmetasec_ml.so` 的 VMP + JIT 里，
且**部分头由 `libsscronet.so` 组装**。要么仿真跑 so，要么让真机算。别浪费时间找"算法还原"。

**关键认知 2**：签名不是瓶颈（100% 成功、48ms）。**抓取受抖音的「设备级限流」+「深度上限」双重约束**：

| 约束 | 现实 |
|---|---|
| 单视频可见深度 | 约 6000-8000 条，超过返回空页（total 13013 的视频只能拿 50-60%） |
| 设备级限流 | 每台设备独立配额（约 20-40 请求/窗口），超出软封 1-3 分钟 |
| 是否 IP 级 | **不是**。实测：池内设备全冷却时，全新设备一次就通 |

推荐参数：并发 4、8 req/s、最多 150 页，30-60 秒拿 6000-7000 条。
详见 `references/fetch-tuning.md`。

## 1. 两条路线的能力边界

| 维度 | unidbg | Xposed + RPC |
|---|---|---|
| 依赖手机 | ❌ 不需要 | ✅ 必须真机常开 |
| 签名速度 | **48ms/次**（常驻服务） | 5-20ms（进程内直调） |
| 并发 | 靠实例池（每实例约 120MB） | 单进程串行 |
| 设备身份 | **可自主注册**（无限设备池） | 用真机身份，一台 |
| 风控暴露面 | 注册多了指纹同质化 | 就是真机，最真实 |
| 工程复杂度 | 高（JNI 桩 / 线程绑定 / 重建） | 中（Xposed 模块 + Sekiro） |
| 适合 | 批量采集、离线签名服务 | 快速验证、少量数据 |

## 2. 两条路线共用的前置事实

| 事实 | 值 |
|---|---|
| 目标包名 | `com.ss.android.ugc.aweme` |
| 签名库 | `libmetasec_ml.so`（40.2.0: 4,525,552 字节, sha256 `7ed8596e2c9ed6422293d1a1522a2d74fc7f5145e2170256eb0ba2d6ed46300b`） |
| 注册加密库 | `libEncryptor.so`（83,928 字节） |
| 唯一 JNI 入口 | `module+0x29b2b4`，签名 `a(IIJLjava/lang/String;Ljava/lang/Object;)Ljava/lang/Object;` |
| 六个头 | `X-Argus` `X-Gorgon` `X-Helios` `X-Khronos` `X-Ladon` `X-Medusa` |
| X-Gorgon 形态 | 52 位十六进制，固定以 `8404` 开头 |
| 注册端点 | `https://log.snssdk.com/service/2/device_register/` |
| 评论端点 | `https://aweme.snssdk.com/aweme/v2/comment/list/` |
| `sig_hash`（40.2.0） | `aea615ab910015038f73c47e45d21466` |

**头字段名只存在于 `libsscronet.so`**，`libmetasec_ml.so` 里一个都没有。
→ 说明 `frameSign` 产出的是签名材料，最终头由 sscronet 组装/格式化。

## 3. 交付纪律

### 3.1 最小可执行原则（硬性）

**适用于所有形态：Xposed+RPC、unidbg CLI、unidbg 常驻服务。**

> 最小可执行 = 能完成目标的**最少代码**，不是最少功能。
> 判定：删掉任意一行，目标还能达成吗？能 → 这行不该在。

三种形态的"最小"：

| 形态 | 文件数 | 行数 | 什么时候才用 |
|---|---|---|---|
| **A. unidbg CLI** | 2 个 Java | ~290 | 验证可行性、几十次签名 |
| **B. Xposed + RPC** | 1 个模块类 + 1 py | ~230 | 有 root 手机、几千条、当天要 |
| **C1. 常驻单实例** | 1 controller + 1 service | ~200 | 连续签名 > 50 次 |
| **C2. C1 + 实例池** | + 1 个 Pool 类 | ~350 | 单实例排队 > 200ms、需设备轮换 |
| **C3. C2 + 注册/限流** | + 2 个 service | ~900 | 需自动造设备、失败率 > 10% |

**先做 A 或 C1，验证通过再按触发器升级。禁止跳档。**

**禁止事项**：
- 探测/基准/调试类代码留在交付物里（`probe*`、`bench`、`directSign` 只该在开发期存在）
- 未被调用的抽象层、为"以后可能"预留的配置项
- 开 12 个实例只用 4 个（预热 150 秒、内存 1.5GB 全浪费）
- 没有需求就上 Spring Boot（51MB fat jar 只为签 10 次名）
- 交付物需要读 3 份文档才能跑起来

**但"最小"≠"能跑就行"**，三条底线不能省：

| 底线 | 说明 |
|---|---|
| 真实请求验证 | 签名出来 ≠ 服务端接受；验收标准是 `status_code==0` 且 `comments` 非空 |
| 失败重建 | 初始化约 1/3 成功率且粘性，**必须**有重建循环（这不是过度设计） |
| README 最小路径 | 一条命令怎么跑、要放哪些文件、预期输出 |

完整清单与反例见 `references/delivery-principles.md`。

### 3.2 其他纪律

- **`-99999` 不等于签名错**：90% 是**请求参数不全**（缺 `cdid`/`device_brand`/`resolution` 等），
  先补齐参数再怀疑算法。详见 `traps.md`。
- **不要把项目常量写进技能**：license、device_id、cdid 属于具体项目，放项目 README。
- **记录三件事**：走了哪条路、用的哪个版本、验证用的什么请求。

## 4. 最短成功路径（照抄即可）

### 走 unidbg

```
① 解出 license（jadx 搜 SecApiImpl / metasec ml 的静态字段）
② 搭 unidbg 工程：加载 libc++_shared → libmetasec_ml → JNI_OnLoad
③ 驱动初始化：0x1000003 → 0x100000c → 0x4000001(17 字段配置) → 0x4000002(handle)
④ 设身份：0x2000002(device_id) / 0x2000003(iid)
⑤ 取头：0x2000006 → String[] 键值对
⑥ 拼**完整参数**请求接口 → status_code 0
```

细节（JNI 桩、配置字段、失败重建）见 `references/unidbg-route.md`。

### 走 RPC

```
① Xposed 模块 hook 到评论 API 的调用点
② 用 Sekiro 把结果以 RPC 暴露出去
③ Python 客户端调 RPC 拿 JSON
```

细节（Gradle 配置、Sekiro 版本、类定位）见 `references/xposed-rpc-route.md`。

## 5. 三分钟自检

```bash
# 设备在线吗
adb devices
# App 版本对不对
adb shell dumpsys package com.ss.android.ugc.aweme | grep versionName
# 网络通不通（抖音报"网络错误"时先查这个，见 traps.md）
adb shell ping -c 1 -W 3 www.baidu.com
# 库在不在
adb shell su -c 'ls /data/app/*/com.ss.android.ugc.aweme*/lib/arm64/'
```

任何一项不对，先修环境，别急着反编译。
