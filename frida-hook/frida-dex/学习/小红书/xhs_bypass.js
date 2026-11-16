/**
 * xhs_bypass.js — 小红书 (com.xingin.xhs) Frida 检测绕过
 *
 * 依据：对 APK 内 libmsaoaidsec.so (armeabi-v7a, 491,388 字节) 的 IDA 分析
 *   sub_127F0  watchdog 线程：while(1){ sub_122BC(); sub_123F0(); ... sleep(4); }
 *   sub_122BC  读 /proc/self/task/<tid>/status，strstr "gum-js-loop" / "gmain" -> exit(0)
 *   sub_123F0  读 /proc/self/fd，lstat 符号链接 + readlink，strstr "linjector" -> exit(0)
 *   sub_17A38  检查 /proc/self/maps（代码平坦化）
 *   字符串加密：周期 3 异或，key = 99 A7 A9
 *
 * 用法：
 *   frida -Uf com.xingin.xhs -l xhs_bypass.js
 *   或已启动的进程：
 *   frida -U -n com.xingin.xhs -l xhs_bypass.js
 *
 * 说明：小红书 APK 只有 armeabi-v7a，在 x86 模拟器上由 Houdini 翻译执行。
 *      libc 层 hook 大多数能生效，但不保证 100%；必要时用 PATCH_BY_OFFSET。
 */

'use strict';

var CFG = {
    blockExit: true,        // 拦 exit/_exit/abort —— 最关键
    hideStrings: true,      // strstr/memmem 特征串过滤
    hidePaths: true,        // openat/open/readlink 路径过滤
    patchByOffset: true,    // 已知构建时直接 patch 检测函数
    traceAbort: true,       // abort/raise 时打印调用栈
    verbose: true
};

// 这份 arm32 构建的特征
var KNOWN = {
    size: 0x780e8,
    threadCheck: 0x122BC,   // /proc/self/task 线程名
    fdCheck: 0x123F0,       // /proc/self/fd linjector
    watchdog: 0x127F0       // 4 秒轮询线程
};

// 需要"假装不存在"的 needle
var NEEDLES = [
    'gum-js-loop', 'gmain', 'linjector', 'frida-agent', 'frida',
    're.frida.server', '/data/local/tmp', 'magisktmp', 'tracerpid',
    '/proc/self/task', '/proc/self/fd'
];

// 仅用于路径类 hook（不要放 /data/local/tmp，会挡到 frida 自己）
var PATHS = ['linjector', 'frida', 'gum-js-loop', 'magisktmp', 're.frida.server'];

var stats = { exit: 0, abort: 0, strstr: 0, path: 0, patched: 0 };

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
        return Thread.backtrace(ctx, Backtracer.FUZZY).slice(0, 8).map(function (a) {
            var m = Process.findModuleByAddress(a);
            return m ? m.name + '+0x' + a.sub(m.base).toString(16) : a.toString();
        }).join(' <- ');
    } catch (e) { return '?'; }
}

/* ---------------- 1. 拦截退出 ---------------- */

function guardExit(name, args) {
    var p = Module.findExportByName(null, name);
    if (!p) return;
    Interceptor.replace(p, new NativeCallback(function (code) {
        stats.exit++;
        log('blocked ' + name + '(' + code + ')  from ' + bt(null));
    }, 'void', args));
    log('hooked ' + name);
}

if (CFG.blockExit) {
    guardExit('exit', ['int']);
    // _exit 在 bionic 上和 exit 可能不同地址
    var pe = Module.findExportByName(null, '_exit');
    if (pe) {
        Interceptor.replace(pe, new NativeCallback(function (code) {
            stats.exit++;
            log('blocked _exit(' + code + ')');
        }, 'void', ['int']));
        log('hooked _exit');
    }
}

if (CFG.traceAbort) {
    ['abort', 'raise'].forEach(function (n) {
        var p = Module.findExportByName(null, n);
        if (!p) return;
        Interceptor.attach(p, {
            onEnter: function () {
                stats.abort++;
                log('!!! ' + n + '() from ' + bt(this.context));
            }
        });
        log('hooked ' + n + ' (trace)');
    });
}

/* ---------------- 2. 字符串过滤 ---------------- */

if (CFG.hideStrings) {
    var strstr = Module.findExportByName(null, 'strstr');
    if (strstr) {
        Interceptor.attach(strstr, {
            onEnter: function (args) {
                var needle = cstr(args[1]);
                var hit = has(needle, NEEDLES);
                this.blocked = !!hit;
                if (hit) { stats.strstr++; log('strstr("' + needle + '") -> NULL'); }
            },
            onLeave: function (r) { if (this.blocked) r.replace(ptr(0)); }
        });
        log('hooked strstr');
    }
    var memmem = Module.findExportByName(null, 'memmem');
    if (memmem) {
        Interceptor.attach(memmem, {
            onEnter: function (args) {
                this.blocked = false;
                var n = args[3].toInt32();
                if (n <= 0 || n > 64) return;
                var needle = null;
                try { needle = args[2].readCString(n); } catch (e) { return; }
                if (has(needle, NEEDLES)) { this.blocked = true; stats.strstr++; }
            },
            onLeave: function (r) { if (this.blocked) r.replace(ptr(0)); }
        });
        log('hooked memmem');
    }
}

/* ---------------- 3. 路径过滤 ---------------- */

if (CFG.hidePaths) {
    function hookPath(fn, idx) {
        var p = Module.findExportByName(null, fn);
        if (!p) return;
        Interceptor.attach(p, {
            onEnter: function (args) {
                var path = cstr(args[idx]);
                var hit = has(path, PATHS);
                this.blocked = !!hit;
                if (hit) { stats.path++; log(fn + ' blocked ' + path); }
            },
            onLeave: function (r) { if (this.blocked) r.replace(ptr(-1)); }
        });
        log('hooked ' + fn);
    }
    hookPath('open', 0);
    hookPath('openat', 1);
    hookPath('access', 0);

    var rl = Module.findExportByName(null, 'readlink');
    if (rl) {
        Interceptor.attach(rl, {
            onEnter: function (a) { this.buf = a[1]; },
            onLeave: function (r) {
                var n = r.toInt32();
                if (n <= 0) return;
                var s = null;
                try { s = this.buf.readCString(n); } catch (e) { return; }
                if (has(s, PATHS)) {
                    stats.path++;
                    log('readlink 篡改: ' + s);
                    var fake = '/dev/null';
                    this.buf.writeUtf8String(fake);
                    r.replace(ptr(fake.length));
                }
            }
        });
        log('hooked readlink');
    }
}

/* ---------------- 4. 按偏移 patch（命中已知构建时） ---------------- */

function tryPatch() {
    var m = Process.findModuleByName('libmsaoaidsec.so');
    if (!m) return false;
    if (m.size !== KNOWN.size) {
        log('libmsaoaidsec.so 大小 ' + m.size + ' != 已知 ' + KNOWN.size + '，跳过 patch');
        return true;
    }
    log('libmsaoaidsec.so base=' + m.base + ' size=0x' + m.size.toString(16));
    [[KNOWN.threadCheck, 'threadCheck'], [KNOWN.fdCheck, 'fdCheck']].forEach(function (pair) {
        try {
            Interceptor.replace(m.base.add(pair[0]), new NativeCallback(function () {
                return 0;
            }, 'int', []));
            stats.patched++;
            log('patched ' + pair[1] + ' @ 0x' + pair[0].toString(16));
        } catch (e) {
            log('patch ' + pair[1] + ' failed: ' + e);
        }
    });
    return true;
}

if (CFG.patchByOffset) {
    var t = 0;
    var timer = setInterval(function () {
        t++;
        if (tryPatch() || t > 240) clearInterval(timer);   // 最多等 120 秒
    }, 500);
}

/* ---------------- 5. 周期统计 ---------------- */

setInterval(function () {
    var m = Process.findModuleByName('libmsaoaidsec.so');
    console.log('[xhs] stats: exit=' + stats.exit + ' abort=' + stats.abort +
        ' strstr=' + stats.strstr + ' path=' + stats.path + ' patched=' + stats.patched +
        ' | lib=' + (m ? '0x' + m.size.toString(16) : 'not loaded'));
}, 15000);
