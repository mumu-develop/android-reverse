---
name: apk-reverse
description: 在逆向 Android APK 或其原生 .so 时使用 —— 定位 Frida/root/反调试检测、还原接口签名（_sig/sign/token）、解密响应、脱壳、驱动 jadx/IDA/Frida。主入口包含：战场勘察、基于证据的路线选择（纯算还原／unidbg 仿真／真机+Xposed+RPC，必须与用户确认后执行）、交付纪律，以及按需加载的参考文档。任何需要还原签名或绕过防护的 Android 应用都应触发。不适用场景：iOS/Mach-O 目标、不涉及 APK 的纯网络协议分析、以及工作对象本身就是 skill 定义时。
---

# Android 逆向 · 主入口

本技能是唯一入口。详细内容在 `references/` 下，**用到再读，不要预读**。

## 路由表

| 你要做的事 | 读哪份 |
|---|---|
| **判断能不能纯算还原、三条路线怎么选** | 本文 §2（**强制闸门**） |
| 还原接口签名 `_sig`/`sign`/`token`、响应解密、`验签失败`、QPS 上不去 | `references/signature.md` |
| 目标库有 VMP/JIT、纯算不可行、要跑 unidbg | `references/emulation.md` |
| App 闪退 / 检测到 root、Frida / 要过反调试 / 脱壳 | `references/anti-debug.md` |
| **要交付代码**（任何形态） | `references/delivery-principles.md` |
| jadx、IDA 的 MCP 怎么调、参数报错、dex→so 串联 | `references/mcp-playbooks.md` |
| 刚拿到 APK，不知道从哪下手 | 本文 §1 → §2 |

```
read <本技能目录>/references/signature.md             # 只在做签名还原时
read <本技能目录>/references/emulation.md             # 只在走 unidbg 仿真时
read <本技能目录>/references/anti-debug.md            # 只在遇到检测/闪退/加固时
read <本技能目录>/references/delivery-principles.md   # 只在要交付代码时
read <本技能目录>/references/mcp-playbooks.md         # 只在调 MCP 或排查报错时
```

## 0. 开工前先确认工具链

**不要假设 MCP 已就绪，先探测再开工。**

| 服务 | 探测 | 就绪标志 |
|---|---|---|
| jadx MCP | `list_mcp_resources(server="jadx")`，或存在 `mcp__jadx__` 工具 | 返回 `JADX-AI-MCP`；端口 `8650` 在听 |
| IDA MCP | `mcp__ida__check_connection()` | `Successfully connected to IDA Pro (open file: xxx)`；端口 `13337` 在听 |

| 情况 | 动作 |
|---|---|
| 两个都通 | 正常开工，定点查询走 MCP |
| 有一个/都不同 | **立刻停下来说明**，给出启动步骤，等用户确认后再继续 |
| 用户明确拒绝启动 | 走 CLI / 纯静态替代路线，并在交付物里标注能力边界 |

**缺工具时的结论强度**（必须写进结论，不能含糊）：

| 缺什么 | 替代 | 结论强度 |
|---|---|---|
| jadx MCP | jadx CLI 全量导出 + grep | 等价 |
| IDA MCP | capstone 自解析 ELF `.dynsym`/`.rela.plt` + 手工反汇编 | **只有汇编级，没有伪代码** |
| 两个都缺 | strings/ELF 静态 + frida 动态验证 | 需动态结果背书 |

两条纪律：用户拒绝后**不要反复劝**；**不要假装用 MCP 出了结论**。

## 1. 60 秒判断战场

### 1.1 壳 / ABI / 位数

```bash
unzip -l target.apk | grep -E "libjiagu|libshell|libDexHelper|assets/.*\.so"   # 壳
unzip -l target.apk | grep "\.so" | awk -F/ '{print $2}' | sort -u            # APK 里的 ABI
adb shell getprop ro.product.cpu.abilist                                      # 设备 ABI
adb shell dumpsys package <pkg> | grep primaryCpuAbi                          # 进程位数
```

- **有 `assets/libjiagu*.so`** → 360 加固，先 `frida-dexdump` 拿真实 dex，别在壳上耗
- **APK 只有 `armeabi-v7a`、设备是 x86_64** → 走 Houdini 翻译，**libc hook 大概率无效**
- **位数没确认就 spawn** → 注入失败或 hook 不到

### 1.2 环境自检（先于一切逆向，能省几小时）

**与逆向无关但最耗时的坑都在这。** 任何一项异常，先修环境：

```bash
adb shell ping -c 1 -W 3 www.baidu.com        # 解析到 240.0.0.x / 无响应 = VPN 假 DNS
adb shell settings get global http_proxy      # 非 ":0" = 抓包代理残留
adb shell dumpsys connectivity | grep DnsAddresses
adb shell ps -A | grep -c frida               # frida-server 死了没
adb shell ps -A | grep -iE "postern|clash|surfboard|vpn"
```

| 现象 | 原因 | 处理 |
|---|---|---|
| App 报"网络错误"，其他 App 正常 | VPN 残留假 DNS（如 `240.0.0.1`） | `am force-stop <vpn包名>`；DNS 不恢复就重启手机 |
| 所有请求超时 | `http_proxy` 指向已停的代理 | `settings put global http_proxy :0` |
| Frida 连不上 | frida-server 自己挂了 | 重启 server + `adb forward tcp:27042 tcp:27042` |

> 这类问题与逆向无关，但会伪装成"检测生效""加固拦截"，排查顺序要放在最前。

## 2. 路线评估与用户确认 —— 强制闸门

> **在写任何还原代码之前，必须先完成本节，并把结论交给用户拍板。**
> **用户没选定路线之前，不要开始实现。**

### 2.0 适用边界（先确认目标属于哪一类）

本技能覆盖 **Android APK / 原生 ELF + jadx/IDA/Frida**。先判断目标形态：

| 签名在哪里 | 走哪条分支 | 说明 |
|---|---|---|
| **Java/Kotlin 层**（含混淆） | 直接纯算，§3 流程 | 最长 1 天，别上仿真 |
| **原生 .so，标准 crypto**（MD5/HMAC/AES/SM3/RSA） | 纯算 | 按 §2.2 的 ①②③ 验证 |
| **原生 .so，VMP/JIT/自毁** | 仿真，`references/emulation.md` | 按 §2.2 的 ①④⑤⑥ 判定 |
| **WASM / JS**（H5 混合壳、webview 内签名） | 浏览器环境仿真（Playwright + 真 JS 引擎） | 本技能只给方向，无现成文档 |
| **Unity / il2cpp** | 先 `il2cpp dump` 出 C#，再判断 | 签名常在 C# 层 |
| **Flutter** | `libapp.so` + Dart snapshot，反汇编方式不同 | 不能直接套 jadx 流程 |
| **iOS / Mach-O** | **不适用本技能** | 需另一套（Mach-O 分析 + Frida for iOS） |

**判断不了就先按 §1 勘察，别假设。**

### 2.1 分层判断：Java 层 / SO 层

| 层 | 勘察动作 | 纯算可行性 |
|---|---|---|
| **Java 层** | jadx 搜签名参数名 → 追到拼接逻辑 | 通常**可行**（能读到完整拼接） |
| **SO 层（轻）** | 未 strip？能定位到标准 crypto 调用？ | **可行** |
| **SO 层（重）** | 见 §2.2 证据清单 | **不可行** |

### 2.2 证据采集清单（六条，必须跑完再下结论）

> **纪律：每条都要贴出实测输出，不许写"感觉是"。**

#### ① crypto 常量扫描 —— 判断是不是"非常规实现"

```python
# save as scan_const.py, run: python scan_const.py libxxx.so
import sys
d = open(sys.argv[1], "rb").read()
pats = {
    "MD5 T0 0xD76AA478":        bytes.fromhex("78a46ad7"),
    "SHA256 K0 0x428A2F98":     bytes.fromhex("982f8a42"),
    "AES S-box head":           bytes.fromhex("637c777bf26b6fc53001672bfed7ab76"),
    "SM3 IV 0x7380166F":        bytes.fromhex("6f168073"),
    "Simon Z 0x3DC94C3A046D678B": bytes.fromhex("8b676d043a4cc93d"),
    "CRC32 poly 0xEDB88320":    bytes.fromhex("2083b8ed"),
}
for name, p in pats.items():
    print("%-28s %d" % (name, d.count(p)))
```

| 结果 | 判定 | 强度 |
|---|---|---|
| 至少 2 类命中、且能看到明显调用点 | 常规实现，**可以纯算** | 硬 |
| 全部 0 命中，但 `strings` 有 "AES"/"SHA" 字样 | 常量被加密/运行时构造 | 硬（走 §2.2 ④ 继续看） |
| 全部 0 命中且无算法字样 | 自研/白盒/VM，**纯算成本极高** | 硬 |

#### ② 签名锚点扫描 —— 判断是否跨库

```bash
for f in lib/*.so; do
  n=$(strings -a "$f" | grep -ciE '^(x-[a-z-]+|sign|_sig|token|nonce|ts)$')
  echo "$(basename $f)  $n"
done
```

| 结果 | 判定 | 强度 |
|---|---|---|
| 参数名与 crypto 调用在**同一个** so | 单库，纯算可行 | 硬 |
| 参数名在一个 so、算法在另一个 so | **跨库**，成本翻倍 | 硬 |
| 所有 so 里都搜不到参数名 | 名字是拼出来的或在 Java 层 | 中（转 §2.1 看 Java 层） |

#### ③ 静态可达性 —— 判断有没有可追踪的锚点

```python
# adrp+add 全扫；掩码不能写成 0x9F00001F（会丢掉 immlo 位）
import struct
def adrp(w):
    if (w & 0x9F000000) != 0x90000000: return None
    immlo = (w >> 29) & 3
    immhi = (w >> 5) & 0x7FFFF
    return ((immhi << 2) | immlo) << 12
```

| 结果 | 判定 | 强度 |
|---|---|---|
| 目标字符串有 ≥3 处 `adrp+add` 引用且能追到计算函数 | 有锚点，纯算可尝试 | 硬 |
| 只有 1-2 处，且只是写字段/打日志 | **无有效锚点** | 硬 |
| 0 处（字符串走间接表） | 只能逐指令读 | 硬 |

#### ④ JIT 判定 —— 算法是否根本不在文件里

```javascript
// frida：在签名返回时，打印 pc 所在的内存映射
var m = Process.findRangeByAddress(this.returnAddress);
console.log(m.file ? m.file.path : 'ANON ' + m.protection);
```

| 结果 | 判定 | 强度 |
|---|---|---|
| 落在匿名可执行页（`ANON rwx`） | **算法是运行时生成的**，静态无解 | 硬 |
| 落在目标 so 的 `r-x` 段 | 算法在文件里，可以静态读 | 硬 |

#### ⑤ JNI 依赖度 —— 重写等于重写半个仿真器

```bash
# unidbg: vm.setVerbose(true)，统计日志里不同签名的种类数
grep -oE 'JNIEnv->[A-Za-z]+' run.log | sort -u | wc -l
grep -oE '->[a-zA-Z]+\([^)]*\)[^ ]*' run.log | sort -u | wc -l
```

| 结果 | 判定 | 强度 |
|---|---|---|
| 回调种类 < 10 | 轻，纯算可行 | 硬 |
| 10-30 | 中，纯算要补不少环境 | 中 |
| **> 30** | 重，**仿真比重写省** | 硬 |

#### ⑥ 密钥来源 —— 算法对了也可能签不出来

```bash
strings -a lib/*.so | grep -oE '\b[0-9a-fA-F]{32,64}\b' | head -20   # 硬编码 key?
```

| 结果 | 判定 | 强度 |
|---|---|---|
| 有 32/64 hex 的字面量，且被用于 crypto 调用 | key 在本地，纯算可行 | 硬 |
| 无硬编码 key，但存在 `license`/`token`/`device_token` 类字段 | **服务端下发/设备绑定** | 硬 |
| 有 key 但由设备信息派生（IMEI/OAID/宽高等） | 可重写，但需一致设备参数 | 中 |

#### 汇总判定

| 命中条数 | 结论 |
|---|---|
| 0-1 条 | **纯算可行**，走方案 A |
| 2-3 条 | 纯算困难，建议仿真或 RPC（让用户选） |
| ≥4 条 | **纯算不可行**，方案 B/C |

> 判定要落到证据，不要凭感觉：
> ✅ "①全 0 命中（附输出）、③仅 2 处且只写字段、④pc 落在 ANON rwx（附日志）"
> ❌ "感觉挺难的"

### 2.3 三条路线对比（必须算出工时再给用户）

| 方案 | 适用 | 难度 | 典型工时 | 产出 | 主要风险 |
|---|---|---|---|---|---|
| **A. 纯算还原** | Java 层 / 轻 SO | 3-5/10 | 0.5-2 天 | 纯代码实现，无 so 依赖 | 密钥拿不到 |
| **B. unidbg 仿真** | 重 SO（VMP/JIT） | 6-9/10 | 2-5 天 | 离线签名服务，可批量 | JNI 桩不全、初始化不稳定 |
| **C. 真机 + Xposed + RPC** | 任意，只要能装模块 | 4-6/10 | 0.5-1 天 | 依赖手机常开的 RPC | 单机串行、不能离线 |

工时估算的参考锚点（跨项目实测区间）：

| 环节 | 耗时 |
|---|---|
| 定位 JNI 入口 + 抓初始化参数 | 2-4 小时 |
| 搭仿真骨架（加载 + JNI 桩 + 初始化链） | 4-8 小时 |
| 攻克初始化失败（重建逻辑） | 2-4 小时 |
| 拼参数打通真实请求 | 2-6 小时 |
| 常驻服务化 + 多身份 | 4-8 小时 |

### 2.4 必须问用户（用这个模板，不要替用户决定）

> 目标 `<包名> <版本>`，签名位于 `<层/so>`，勘察结论：
>
> - **证据**：`①常量扫描 … ②锚点 … ③可达性 … ④JIT … ⑤JNI … ⑥key …`（逐条贴输出）
> - **纯算可行性**：`可行 / 困难 / 不可行`
> - **方案 A 纯算**：难度 `X/10`，预计 `N` 天
> - **方案 B 仿真**：难度 `Y/10`，预计 `M` 天，产出离线服务（可批量、不依赖手机）
> - **方案 C 真机+RPC**：难度 `Z/10`，预计 `K` 小时，但要手机常开、单机串行
>
> 我建议走 `方案?`，因为 `<理由>`。**你选哪条？**

**闸门纪律**：

| 情况 | 动作 |
|---|---|
| 用户没回答 | **停住等**，不要"先做着看看" |
| 用户选了较难的路线 | 记录理由，按用户选择执行 |
| 勘察后发现判断错了（以为能纯算，实际是 VMP） | **立即回来重新确认**，不要自己改路线 |
| 中途成本超出预估 2 倍 | 回来重新报工时 |

## 3. 标准流程（路线确定后）

```
① APK 层：jadx CLI 全量导出 → grep 定位请求构造类 / native 声明
② 边界：找到 System.loadLibrary + native 方法名
③ 路线判定：按 §2 得出结论（纯算 / 仿真 / RPC）
④ SO 层：符号是否 strip？未 strip 直接按 JNI 名定位
⑤ 字符串：可能加密，先试阿里聚安全 key 99 A7 A9（见 anti-debug.md）
⑥ 动态：静态搞不定就 hook 系统边界（见 anti-debug.md）
⑦ 定位凶手：returnAddress → 模块名+偏移（见 anti-debug.md）
```

**两条腿走路**：

- **批量**（几万文件里找可疑点）→ jadx CLI 全量导出 + grep
- **定点**（已知类名/函数名，要源码或伪代码）→ MCP

```bash
jadx -d out --no-res target.apk            # 需要 JADX_CONFIG_DIR/CACHE/TMP 可写
grep -rn "loadLibrary\|native " out/sources | head
```

**走仿真时**：直接读 `references/emulation.md`，不要从零试。

## 4. 交付纪律

### 4.1 最小可执行（硬性）

> 最小可执行 = 能完成目标的**最少代码**，不是最少功能。
> 判定：删掉任意一行，目标还能达成吗？能 → 这行不该在。

档位、升级触发器、禁止事项、交付前自检，全部见 `references/delivery-principles.md`。

一句话：**先做能验证假设的最小版本，验证通过再按需升级；任何"以后可能用到"的代码都不该进交付物。**

### 4.2 验证标准（三层，缺一不可）

| 层 | 判据 |
|---|---|
| ① HTTP | `200` |
| ② 业务码 | 业务成功码（不是 `success:false` / `code!=0` / 各家自定义错误码） |
| ③ 数据 | 返回体**非空**且结构符合预期 |

**只满足 ① 的结论一律视为未验证。** 三种常见假象：

| 假象 | 真相 |
|---|---|
| `200` + 业务码 = 错误码 | 参数不全 / 签名不匹配（先查参数，别急着改算法） |
| `200` + 成功码 + **数据为空** | 限流软封禁（看起来完全正常），等几分钟或换出口 IP |
| `200` + 成功码 + 旧数据 | 服务端缓存；换参数或加时间戳验证 |

### 4.3 其他

- **结论前先写清走了哪条路**：MCP / CLI / 纯静态 / 仿真，以及由此带来的可信度边界
- 检测点表：`so + 偏移 + 手法 + 判定条件`
- 绕过脚本：patch 优先，兜底 hook，带 `stats` 心跳
- API 客户端：常量 + 签名函数 + **一次真实请求验证**
- 具体项目的常量（盐、密钥、证书指纹）留在项目 README，**别写进技能**
- **记录三件事**：走了哪条路、用的哪个版本、验证用的什么请求

## 5. 工具坑

| 坑 | 现象 | 处理 |
|---|---|---|
| **用 PowerShell 改中文文档** | 文件里中文变「锛/鐨/涓」乱码且开头带 BOM(`EF BB BF`) | PS5.1 的 `Get-Content -Raw` 默认按 GBK 读 UTF-8，写回时二次转码。改用 `[IO.File]::WriteAllText($p,$s,[Text.UTF8Encoding]::new($false))` 或专用写文件工具 |
| **`adb shell` 引号地狱** | 复杂命令（正则/通配符/管道）被本机 shell 吞掉，报 `no closing quote` | 把命令写成 `.sh` 文件，`adb push` 到 `/data/local/tmp/`，再 `adb shell su -c 'sh /data/local/tmp/x.sh'` |
| **`pm clear` 以为能重置身份** | 清数据后设备标识原样回来 | 身份与**硬件指纹**绑定，清数据不重置。要新身份只能改指纹或自己走注册流程 |
| pip 装包挂起 | 无输出、进程烧 CPU | 换国内镜像 `-i https://pypi.tuna.tsinghua.edu.cn/simple`；写用户目录被沙箱拦时报 `Check the permissions`，需提权 |
| **Xposed 模块装了不生效** | 模块日志一条没有 | LSPosed 不热注入，必须 `am force-stop <pkg>` 后重新 `am start` |
