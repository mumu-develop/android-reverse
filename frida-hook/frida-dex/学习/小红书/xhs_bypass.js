/**
 * xhs_bypass.js — 小红书 (com.xingin.xhs) 轻量检测绕过
 * ================================================================
 * v3：解决「spawn 后界面卡死」
 *
 * 卡死原因
 * --------
 * v2 默认挂了 strstr / memmem / open / openat / access / readlink 六个高频函数。
 * 启动阶段这些调用有数万次，每次都 JS<->native 往返，JS 单线程被占满 -> 主线程拖死。
 *
 * v3 策略
 * -------
 *   1. 默认只拦 exit / _exit（调用极少，开销可忽略）。检测命中后进程也不会退出。
 *   2. 高频 hook 全部默认关闭，需要时改 CFG.hotHooks = true。
 *   3. 即使开启，也可以用 CFG.hotHookDelayMs 延迟到启动完成后再挂。
 *   4. offset patch 改成一次性尝试，失败就放弃（该库被加壳，磁盘偏移对不上运行时）。
 *
 * 用法
 * ----
 *   spawn（可赶在库加载前）：
 *     frida -Uf com.xingin.xhs -l xhs_bypass.js
 *   已启动进程：
 *     frida -U -n com.xingin.xhs -l xhs_bypass.js
 *     frida -H 127.0.0.1:27043 -p <pid> -l xhs_bypass.js
 */

'use strict';

var LIB = 'libmsaoaidsec.so';

var CFG = {
    // 核心：吞掉 exit，检测命中也不退出
    exitGuard: true,

    // 高频 hook 默认关闭（开了会卡界面）
    hotHooks: false,
    // 即使开启，也延迟这么久再挂，避开启动高峰
    hotHookDelayMs: 15000,

    // 按偏移 patch（加壳库大概率对不上，失败会快速放弃）
    patchByOffset: true,

    verbose: true
};

// 这份构建的三个检测函数偏移（磁盘文件里的值；加壳后运行时可能对不上）
var KNOWN = {
    threadCheck: 0x122BC,
    fdCheck: 0x123F0,
    watchdog: 0x127F0,
    prologue: 0xB5F0
};

var NEEDLES = [
    'gum-js-loop', 'gmain', 'linjector', 'frida-agent', 'frida',
    're.frida.server', 'magisktmp', 'tracerpid'
];
var PATHS = ['linjector', 'frida', 'gum-js-loop', 'magisktmp', 're.frida.server'];

var stats = { exit: 0, strstr: 0, path: 0, patched: 0 };
var patchedBase = null;
var patchAttempts = 0;

function log(m) { if (CFG.verbose) console.log('[xhs] ' + m); }

function cstr(p) {
    if (!p || p.isNull()) return null;
    try { return p.readCString(); } catch (e) {
        try { return p.readUtf8String(256); } catch (e2) { return null; }
    }
}

function has(s, list) {
    if (!s) return null;
    var l = s.toLowerCase();
    for (var i = 0; i < list.length; i++) if (l.indexOf(list[i]) !== -1) return list[i];
    return null;
}

function bt(ctx) {
    try {
        return Thread.backtrace(ctx, Backtracer.FUZZY).slice(0, 6).map(function (a) {
            var m = Process.findModuleByAddress(a);
            return m ? m.name + '+0x' + a.sub(m.base).toString(16) : a.toString();
        }).join(' <- ');
    } catch (e) { return '?'; }
}

/* ---------------- 1. 核心：拦 exit / _exit ---------------- */

if (CFG.exitGuard) {
    ['exit', '_exit'].forEach(function (name) {
        var p = Module.findExportByName(null, name);
        if (!p) return;
        try {
            Interceptor.replace(p, new NativeCallback(function (code) {
                stats.exit++;
                log('拦截 ' + name + '(' + code + ')  ← 检测命中，已阻止退出');
            }, 'void', ['int']));
            log('已挂 ' + name);
        } catch (e) {
            log('挂 ' + name + ' 失败: ' + e);
        }
    });
}

/* ---------------- 2. 可选：高频 hook（默认关） ---------------- */

function installHotHooks() {
    log('开始挂高频 hook（会明显增加开销）');

    var strstr = Module.findExportByName(null, 'strstr');
    if (strstr) {
        Interceptor.attach(strstr, {
            onEnter: function (args) {
                this.block = false;
                // 先做最便宜的判断：调用者模块
                var m = Process.findModuleByAddress(this.returnAddress);
                if (!m || m.name !== LIB) return;
                var needle = cstr(args[1]);
                if (has(needle, NEEDLES)) {
                    this.block = true;
                    stats.strstr++;
                    log('strstr("' + needle + '") -> NULL');
                }
            },
            onLeave: function (r) { if (this.block) r.replace(ptr(0)); }
        });
        log('已挂 strstr');
    }

    function hookPath(fn, idx) {
        var p = Module.findExportByName(null, fn);
        if (!p) return;
        Interceptor.attach(p, {
            onEnter: function (args) {
                this.block = false;
                var m = Process.findModuleByAddress(this.returnAddress);
                if (!m || m.name !== LIB) return;
                var path = cstr(args[idx]);
                if (has(path, PATHS)) {
                    this.block = true;
                    stats.path++;
                    log(fn + ' 拦截: ' + path);
                }
            },
            onLeave: function (r) { if (this.block) r.replace(ptr(-1)); }
        });
        log('已挂 ' + fn);
    }
    hookPath('openat', 1);
    hookPath('open', 0);
}

if (CFG.hotHooks) {
    if (CFG.hotHookDelayMs > 0) {
        log('高频 hook 将在 ' + CFG.hotHookDelayMs + 'ms 后挂载');
        setTimeout(installHotHooks, CFG.hotHookDelayMs);
    } else {
        installHotHooks();
    }
}

/* ---------------- 3. 一次性 offset patch ---------------- */

function prologueOk(base, off) {
    try {
        return base.add(off).readU16() === KNOWN.prologue;
    } catch (e) {
        return false;
    }
}

function patchLib() {
    var m = Process.findModuleByName(LIB);
    if (!m) return false;
    if (patchedBase && patchedBase.equals(m.base)) return true;

    var targets = [['threadCheck', KNOWN.threadCheck], ['fdCheck', KNOWN.fdCheck]];
    var done = 0;
    targets.forEach(function (t) {
        if (!prologueOk(m.base, t[1])) return;
        try {
            Interceptor.replace(m.base.add(t[1]), new NativeCallback(function () {
                return 0;
            }, 'int', []));
            stats.patched++;
            done++;
            log('已中和 ' + t[0]);
        } catch (e) {
            log('patch ' + t[0] + ' 失败: ' + e);
        }
    });

    if (done > 0) patchedBase = m.base;
    else log('偏移与运行时镜像不符（加壳），跳过 offset patch');
    return true;
}

if (CFG.patchByOffset) {
    var timer = setInterval(function () {
        patchAttempts++;
        patchLib();
        if (patchedBase || patchAttempts > 4) clearInterval(timer);
    }, 700);
}

/* ---------------- 4. 心跳 ---------------- */

setInterval(function () {
    var m = Process.findModuleByName(LIB);
    console.log('[xhs] stats: exit=' + stats.exit + ' strstr=' + stats.strstr +
        ' path=' + stats.path + ' patched=' + stats.patched +
        ' | lib=' + (m ? '0x' + m.size.toString(16) : 'not loaded') +
        ' | hotHooks=' + (CFG.hotHooks ? 'on' : 'off'));
}, 20000);
