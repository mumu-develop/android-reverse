# 反调试 / 检测绕过 / 脱壳

> 由 `apk-reverse` 按需引用。只在确实遇到检测、闪退、加固时才读这份。

## 0. 先建基线（跳过这步，后面所有"有效"都可能是假的）

把 frida-server 换成**官方版**，跑一个空脚本 spawn 目标 app，记下从 resume 到进程消失的秒数：

```bash
python frida_test.py empty.js 20 <pkg>        # 看 RESULT 与 "PROCESS GONE after X s"
```

这是判断"补丁有没有用"的**唯一参照**：

| 现象 | 说明 |
|---|---|
| 空脚本活到 X 秒，打补丁后还是 X 秒 | 补丁无效 |
| 空脚本 X 秒死，打补丁后 > 3X 秒 | 可能有效，继续按「补丁验收四条」确认 |
| 换 florida / 魔改 server 后空脚本就不死了 | **环境把检测掩盖了**，此时任何补丁都测不出效果 |

**踩过的坑**：用 florida 时 app 自始至终不死，"补丁有效"的结论跑了很久，最后发现是 server 的隐藏能力在起作用，补丁本身空转。

## 1. 先决定打哪一层

同一条检测链，从不同位置下手，代价和成功率差一个数量级：

| 层 | 下手点 | 打中之后 | 依赖什么 |
|---|---|---|---|
| 进程级 | 换 frida server / 改 agent 特征 | 根本没痕迹 | 什么都不用逆 |
| 模块级 | `android_dlopen_ext` + `call_constructors` | 构造函数期就动手，零窗口期 | 模块名 |
| **线程级** | `pthread_create` 的 `start_routine` | **整段巡检逻辑不存在** | 只要知道线程是谁起的 |
| 函数级 | 判决函数 `return 0` | 单次判定被伪造，巡检仍在转 | 函数边界 |
| 判决点 | `strcmp`/`strstr` 之后的分支 | 需要读懂逻辑 | 伪代码理解 |
| 退出点 | `_exit` / `abort` | 最晚，多数已经判定完了 | —— |

**结论：位置越靠前，越不依赖对逻辑的理解。** 读不懂判决逻辑时，优先考虑线程级。

## 2. 三种检测范式（几乎覆盖全部）

| 范式 | 具体特征 |
|---|---|
| **字符串扫描** | `/proc/self/fd`+`linjector`；`/proc/self/maps`+`frida-agent`/`/data/local/tmp`；`/proc/self/task/*/status`+`gum-js-loop`/`gmain` |
| **反调试** | `/proc/self/status` 的 `TracerPid`；`ptrace(PTRACE_ATTACH)`；tracer 的 `PPid` 校验 |
| **环境** | `MAGISKTMP`、`/system/xposed.prop`；`__system_property_get` 含 `adb`；APK 证书指纹 |

杀进程的收尾动作：`_exit(0)`（阿里聚安全）、`exit(0)`、`abort()`、`dlclose`+`munmap`（网易易盾，抹掉 agent 但 App 存活）。

## 3. 阿里聚安全字符串解密

周期 3 异或，密钥固定 **`99 A7 A9`**（B 站/小红书/豆瓣三份都相同）：

```python
key = [0x99, 0xA7, 0xA9]
plain = bytes(c ^ key[i % 3] for i, c in enumerate(cipher))
```

解出来的标志串：`/proc/%d/status`、`TracerPid:`、`PPid:`、`adb`、`/proc/self/{fd,task,maps}`、`linjector`、`gum-js-loop`、`gmain`、`MAGISKTMP`。

扫描整个 `.rodata` 即可拿到完整检测清单，比 strings 有效得多。

## 4. 动态：hook 边界，别 hook 业务

**抓签名**（最快见效）：

```javascript
var Mac = Java.use('javax.crypto.Mac');
Mac.init.overload('java.security.Key').implementation = function (k) {
    console.log('[KEY] ' + k.getEncoded()); return this.init(k);
};
Mac.doFinal.overload('[B').implementation = function (d) {
    console.log('[IN] ' + d); return this.doFinal(d);   // 只打印，热路径慎用
};
```

**定位「谁动手」**（核心技巧）：

```javascript
Interceptor.attach(fn, {
  onEnter: function (a) {
    var ra = this.returnAddress;
    var m = Process.findModuleByAddress(ra);
    console.log(fn + ' from ' + (m ? m.name + '+0x' + ra.sub(m.base).toString(16) : ra));
  }
});
```

要抓的动作：`exit` `_exit` `abort` `raise` `kill` `tgkill` `munmap`(>4MB) `dlclose` `mprotect`。

**确认 App 是否真死**：`adb shell ps -A | grep <pkg>` —— frida 报 `Process terminated` 常常只是会话被掐，App 还活着。

### 线程入口抹除（读不懂检测逻辑时的最优解）

检测几乎都跑在独立线程里。与其读判定逻辑，不如让线程一起来就返回。

```javascript
var WATCH = /msaoa|nesec|secexe|yidun/i;
var STUB_X64 = [0x31, 0xC0, 0xC3];                 // xor eax,eax; ret
// arm64: mov x0,#0; ret → [0x2a,0x00,0x80,0xd2, 0xc0,0x03,0x5f,0xd6]（8 字节）

Interceptor.attach(Module.findExportByName(null, 'pthread_create'), {
  onEnter: function (a) {
    var m = Process.findModuleByAddress(a[2]);      // a[2] = start_routine
    if (!m || !WATCH.test(m.name)) return;
    Memory.patchCode(a[2], 3, function (code) { code.writeByteArray(STUB_X64); });
  }
});
```

三条硬约束，缺一条就失败：

| 约束 | 违反的后果 |
|---|---|
| 必须在 `onEnter`（线程创建**之前**） | `onLeave` 时线程已在跑，改晚了 |
| 必须用 `Memory.patchCode`，不能 `Interceptor.replace` | 在拦截回调里 replace 会**死锁**：当前线程停在 trampoline 里，replace 要等全局安全点 |
| 不能挪进 `setTimeout(0)` 绕过上一条 | 部分 app 的 ctor 回调返回后定时器队列不再被服务，补丁永远不执行 |

**只写 3 字节，不装 trampoline**：`ret` 之后那段残留指令永远执行不到；代价是原函数彻底不可用，要可逆就提前 `Memory.readByteArray` 存原字节。

**覆盖面**：一个 app 常有好几个安全 so 各自起线程（实测豆瓣四个：`libmsaoaidsec.so`、`libmsaoaidauth.so`、`libnesec-x86.so`、`libsecexe.so`），漏一个就可能白干——用正则一次全盖住。

**副作用**：这些线程可能同时承担正常业务（设备指纹上报、风控埋点）。先全抹验证有效，再逐个放回找最小集合，最后回归测登录/支付。

## 4.5 hook 装了但不触发 —— 排查树

**"hook 不触发"有 5 种完全不同的原因，按顺序排，别跳。**

| # | 检查 | 判据 | 处理 |
|---|---|---|---|
| 1 | 模块是否已加载？ | `Process.findModuleByName('libX.so')` 返回 null | 用 `dlopen` 钩子等加载时机；或轮询 |
| 2 | 地址是否是**跳板**？ | 首字节 `50 00 00 58`（`ldr x16,#8; br x16`） | 读 `addr+8` 处的指针才是真函数 |
| 3 | 是否**线程绑定**？ | JNI 环境是 per-thread 的 | 必须在创建它的线程上调用，或改成在同一线程 init |
| 4 | 是否被保护壳**改写**？ | 文件偏移的字节与运行时字节不一致 | 以运行时字节为准，重新定位 |
| 5 | 是否走的是**另一条路径**？ | 目标 App 根本不调用你 hook 的那个入口 | hook 全部候选入口，统计谁真正被调用 |

**实测（某 SDK）**：

```
文件里 0x29b2b4:  e1 03 00 aa ...   ; mov x1,x0（JNI wrapper）
运行时 0x29b2b4:  50 00 00 58 ...   ; ldr x16,#8; br x16（跳板）
```

按文件偏移 hook → 调用数恒为 0；按 `+8` 解析出真函数 → 立刻抓到调用。

**验证 hook 是否真的装上了**：

```javascript
Interceptor.attach(addr, { onEnter() { console.log('[hit]'); } });
// 然后主动触发一次已知会走这条路的操作（切页/刷新/打开详情）
// 仍然 0 次 → 先怀疑地址，不要怀疑"没调用"
```

**"调用数为 0" 的三种典型误判**：

| 误判 | 真相 |
|---|---|
| "这个函数没被用过" | 地址错了（跳板/体内地址） |
| "SDK 没启用" | 走的是另一个入口/另一个 so |
| "App 有检测" | 模块还没加载就 hook 了 |

**定位真入口的通用手段**：hook `RegisterNatives`（JNIEnv 表项 215），
读 `JNINativeMethod {name, sig, fnPtr}` 三元组，`fnPtr` 落在目标模块内的就是真入口。

## 5. 环境陷阱（按踩坑频率排序）

| 坑 | 现象 | 处理 |
|---|---|---|
| **热路径 `console.log`** | app 卡死，主线程 futex 卡在 `memfd:jit-cache` | hook 里只计数，定时批量输出 |
| **`Interceptor.replace(exit/_exit)`** | frida JS 线程饿死，`setInterval` 全不跑 | 别 replace exit；改用 patch 目标函数 |
| **Houdini 翻译** | arm so 在 x86 模拟器上，libc hook 全静默 | 换 arm64 真机，或只做静态 |
| **官方 frida-server** | 注入即被踢 | 换 florida/魔改版 |
| **`_Exit` == `_exit`** | `already replaced this function` 中断脚本 | 按指针去重 |
| **spawn 超时** | `unexpectedly timed out` | `dev.spawn([pkg], timeout=60)` |
| **adb forward 失效** | `unable to connect to remote frida-server` | 重设 `adb forward tcp:27042 tcp:27042` |
| **端口占用** | `Address already in use` | `netstat -tlnp \| grep 27042` → `kill -9 <pid>` |
| **在拦截回调里 `Interceptor.replace`** | app 直接挂住、进程 D 状态，`setInterval` 全静默 | 改用 `Memory.patchCode` 写字节；回 JS 线程的 `setTimeout(0)` 方案部分 app 也不可行 |
| **定时器静默** | 钩子照常触发，但 `setInterval` 一次都不跑 | 心跳改成事件计数触发，别把关键逻辑挂在定时器上 |
| **静态偏移打在自解密代码上** | 字节确实变了，几秒后自己变回去 | 打完 2s / 5s 各回读一次字节 |
| **抄来的偏移不是函数头** | 改完直接崩，SIGSEGV 落在偏移附近 | 见下面「函数头校验」 |
| **只 hook `lstat`/`readlink` 想弄瞎目录枚举** | 调用次数一点没降 | 枚举走 `readdir`；`getdents64` 在 bionic 里没有导出 |
| **只打一个 so 的补丁** | 多撑一两秒还是死 | 先跑归因，把所有安全 so 的线程都列出来 |
| **`adb shell` 引号地狱** | 复杂命令（正则/通配符/管道）被本机 shell 吞掉，报 `no closing quote` | 写成 `.sh` 文件 `adb push` 到 `/data/local/tmp/`，再 `adb shell su -c 'sh /data/local/tmp/x.sh'` |
| **`pm clear` 以为能重置身份** | 清数据后 device_id 原样回来 | 身份与**硬件指纹**绑定，清数据不重置；要新身份只能改指纹或自己走注册流程 |

### 函数头校验（拿到任何偏移的第一件事）

```
get_function_by_address("0x1AF20")
```

| 返回值 | 判断 |
|---|---|
| `name` 就是 `sub_<偏移>` | 是函数入口，可以用 |
| `name` 与偏移不符（落进别的函数体内） | **不能用**，改用返回的那个 `name` 的地址 |
| `size` 覆盖不到该偏移 | 同上，是体内地址 |

实测过的反例：某脚本对 `base + 0x11E60 + 1` 做 `Interceptor.replace`，而 `0x11E60` 落在 `sub_11E20` 体内 0x40 字节处，字节是 `eb 0d`（2 字节短跳）——覆盖后 `jz` 的落点 `0x11E62` 变成半条指令，执行到那里必然崩。**抄来的偏移一律当体内地址处理，先校验再动手。**

### 补丁验收四条（缺一条都可能是在自欺）

1. **字节回读**：写完立即读一次，再在 2 秒、5 秒各读一次（对付自解密）
2. **行为消失**：对应的 `open` / `lstat` / `pthread_create` 序列真的没了
3. **存活时长**：超过基线的 3 倍
4. **UI 真的在动**：截图看到倒计时/动画在走，不是假死

只满足第 3 条的，大概率是运气或假死。

**patch 优先于 hook，但要打在正确的层**：让检测函数返回"安全值"比拦系统调用稳。前提是那个函数真的是判决点——实测某库里那个看名字像"TracerPid 检查"的函数，15 秒内一次都没被调用，补丁纯空转。所以 patch 完必须按上面四条逐条确认，**字节变了不等于生效了**。
