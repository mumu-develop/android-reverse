/**
 * bili_bypass.js — 绕过 B 站 libmsaoaidsec.so 的 Frida / 反调试检测
 *
 * 静态分析依据（x86 版 libmsaoaidsec.so）：
 *   - 字符串周期 3 异或加密（key = 99 A7 A9），已还原 626 条
 *   - /proc/self/fd  + "linjector"            -> _exit(0) 静默闪退
 *   - /proc/self/task + "gum-js-loop"/"gmain" -> 线程名检测
 *   - /proc/self/maps + "frida-agent"/"/data/local/tmp"
 *   - /proc/<pid>/status + "TracerPid:"
 *   - MAGISKTMP、"u:r:zygote:s0"
 *   - ptrace 簇：sub_11820 / sub_11BA0 / sub_12650
 *
 * 只用 libc 层 hook，不依赖 ABI 偏移，arm64 / x86 通用。
 *
 * 用法：
 *   frida -H 127.0.0.1:27042 -f tv.danmaku.bili -l bili_bypass.js
 *   frida -H 127.0.0.1:27042 -n <进程名> -l bili_bypass.js
 *
 * 验证：
 *   adb logcat | findstr /i "bypass msaoa"
 */

'use strict';

/* ============================== 配置 ============================== */

var CFG = {
    blockExit: true,       // 拦截 _exit / exit —— 最关键
    hideStrings: true,     // 拦截 strstr / memmem 对特征串的查找
    hidePaths: true,       // 拦截 open / fopen / stat / readlink 对 frida 路径的访问
    logPtrace: true,       // 只记录 ptrace，不改变行为
    verbose: true
};

// "假装不存在"的字符串（大小写不敏感）
var NEEDLES = [
    'linjector',
    'frida',
    'gum-js-loop',
    'pool-frida',
    'gmain',
    'gdbus',
    'magisktmp',
    '/data/local/tmp',
    'tracerpid',
    'xposed',
    'substrate'
];

// 只用于路径类 hook。注意不要包含 /data/local/tmp，
// 否则会把 frida 自己的文件操作也挡掉。
var PATHS = [
    'linjector',
    'frida',
    'gum-js-loop',
    're.frida.server',
    'magisktmp',
    'xposed'
];

/* ============================== 工具 ============================== */

function log(msg) {
    if (CFG.verbose) console.log('[bypass] ' + msg);
}

function readCStr(p) {
    if (!p || p.isNull()) return null;
    try {
        return p.readCString();
    } catch (e) {
        try {
            return p.readUtf8String(256);
        } catch (e2) {
            return null;
        }
    }
}

function containsAny(s, list) {
    if (!s) return null;
    var low = s.toLowerCase();
    for (var i = 0; i < list.length; i++) {
        if (low.indexOf(list[i]) !== -1) return list[i];
    }
    return null;
}

function callerInfo(ctx) {
    try {
        var bt = Thread.backtrace(ctx, Backtracer.ACCURATE).slice(0, 3);
        return bt.map(function (a) {
            var m = Process.findModuleByAddress(a);
            return m ? (m.name + '+0x' + a.sub(m.base).toString(16)) : a.toString();
        }).join(' <- ');
    } catch (e) {
        return 'unknown';
    }
}

var hits = { strstr: 0, memmem: 0, path: 0, exit: 0, ptrace: 0 };

/* ========================= 1. 阻止静默退出 ========================= */

var replaced = {};

function installExitGuard(name) {
    var p = Module.findExportByName(null, name);
    if (!p) return;
    var key = p.toString();
    // bionic 上 _exit / _Exit / exit 可能是同一个地址，重复 replace 会抛异常
    if (replaced[key]) {
        log(name + ' same address as ' + replaced[key] + ', skipped');
        return;
    }
    Interceptor.replace(p, new NativeCallback(function (code) {
        hits.exit++;
        log('blocked ' + name + '(' + code + ') caller=' + callerInfo(null));
    }, 'void', ['int']));
    replaced[key] = name;
    log('hooked ' + name);
}

if (CFG.blockExit) {
    installExitGuard('_exit');
    installExitGuard('_Exit');
    installExitGuard('exit');
}

/* ========================= 2. 字符串特征查找 ========================= */

if (CFG.hideStrings) {
    var strstr = Module.findExportByName(null, 'strstr');
    if (strstr) {
        Interceptor.attach(strstr, {
            onEnter: function (args) {
                var needle = readCStr(args[1]);
                var hit = containsAny(needle, NEEDLES);
                this.blocked = !!hit;
                if (hit) {
                    hits.strstr++;
                    log('strstr hit needle="' + needle + '" -> NULL');
                }
            },
            onLeave: function (retval) {
                if (this.blocked) retval.replace(ptr(0));
            }
        });
        log('hooked strstr');
    }

    var memmem = Module.findExportByName(null, 'memmem');
    if (memmem) {
        Interceptor.attach(memmem, {
            onEnter: function (args) {
                var nlen = args[3].toInt32();
                this.blocked = false;
                if (nlen <= 0 || nlen > 64) return;
                var needle = null;
                try { needle = args[2].readCString(nlen); } catch (e) { return; }
                var hit = containsAny(needle, NEEDLES);
                if (hit) {
                    this.blocked = true;
                    hits.memmem++;
                    log('memmem hit needle="' + needle + '" -> NULL');
                }
            },
            onLeave: function (retval) {
                if (this.blocked) retval.replace(ptr(0));
            }
        });
        log('hooked memmem');
    }
}

/* ========================= 3. 路径访问过滤 ========================= */

if (CFG.hidePaths) {
    function hookSimple(fnName, argIndex) {
        var p = Module.findExportByName(null, fnName);
        if (!p) return;
        Interceptor.attach(p, {
            onEnter: function (args) {
                var path = readCStr(args[argIndex]);
                var hit = containsAny(path, PATHS);
                this.blocked = !!hit;
                if (hit) {
                    hits.path++;
                    log(fnName + ' blocked: ' + path);
                }
            },
            onLeave: function (retval) {
                if (this.blocked) retval.replace(ptr(-1));
            }
        });
        log('hooked ' + fnName);
    }

    hookSimple('open', 0);
    hookSimple('openat', 1);
    hookSimple('stat', 0);
    hookSimple('lstat', 0);
    hookSimple('access', 0);

    // fopen 返回 FILE*，失败要返回 NULL
    ['fopen', 'fopen64'].forEach(function (fn) {
        var p = Module.findExportByName(null, fn);
        if (!p) return;
        Interceptor.attach(p, {
            onEnter: function (args) {
                var path = readCStr(args[0]);
                var hit = containsAny(path, PATHS);
                this.blocked = !!hit;
                if (hit) {
                    hits.path++;
                    log(fn + ' blocked: ' + path);
                }
            },
            onLeave: function (retval) {
                if (this.blocked) retval.replace(ptr(0));
            }
        });
        log('hooked ' + fn);
    });

    // readlink：把 frida 相关的链接目标改成 /dev/null
    var readlink = Module.findExportByName(null, 'readlink');
    if (readlink) {
        Interceptor.attach(readlink, {
            onEnter: function (args) {
                this.buf = args[1];
                this.size = args[2].toInt32();
            },
            onLeave: function (retval) {
                var n = retval.toInt32();
                if (n <= 0) return;
                var s = null;
                try { s = this.buf.readCString(n); } catch (e) { return; }
                var hit = containsAny(s, PATHS);
                if (hit) {
                    hits.path++;
                    log('readlink patched: ' + s);
                    var fake = '/dev/null';
                    this.buf.writeUtf8String(fake);
                    retval.replace(ptr(fake.length));
                }
            }
        });
        log('hooked readlink');
    }
}

/* ========================= 4. ptrace 观察 ========================= */

if (CFG.logPtrace) {
    var ptrace = Module.findExportByName(null, 'ptrace');
    if (ptrace) {
        Interceptor.attach(ptrace, {
            onEnter: function (args) {
                hits.ptrace++;
                log('ptrace(req=' + args[0].toInt32() + ', pid=' + args[1].toInt32() + ')');
            }
        });
        log('hooked ptrace (observe only)');
    }
}

/* ============ 5. 安全库加载监视（ld 内不发消息，只记数组） ============ */

var loadedSec = [];
var dlEvents = [];

['dlopen', 'android_dlopen_ext'].forEach(function (fn) {
    var a = Module.findExportByName(null, fn);
    if (!a) return;
    Interceptor.attach(a, {
        onEnter: function (args) {
            try {
                var p = args[0];
                if (p.isNull()) return;
                var s = p.readCString();
                if (s && /msaoa|sec|bili|CtaApi/i.test(s)) {
                    if (dlEvents.length < 200) dlEvents.push(s);
                }
            } catch (e) { }
        }
    });
});

setInterval(function () {
    if (dlEvents.length) {
        dlEvents.forEach(function (s) { console.log('[bypass] dlopen: ' + s); });
        dlEvents = [];
    }
}, 400);

/* ============ 6. 周期状态（每 10 秒，共 3 分钟） ============ */

var ticks = 0;
var lastMod = null;
var timer = setInterval(function () {
    ticks++;
    var mod = Process.findModuleByName('libmsaoaidsec.so');
    var modDesc = mod ? (mod.base + ' size=0x' + mod.size.toString(16)) : 'not loaded';

    // 只在"状态变化"或每 30 秒时打印，避免刷屏
    if (modDesc !== lastMod || ticks % 3 === 0) {
        console.log('----------------------------------------');
        console.log('[bypass] t=' + (ticks * 10) + 's arch=' + Process.arch +
            ' module=' + modDesc);
        console.log('[bypass] stats: strstr=' + hits.strstr +
            ' memmem=' + hits.memmem +
            ' path=' + hits.path +
            ' exit=' + hits.exit +
            ' ptrace=' + hits.ptrace);
        lastMod = modDesc;
    }

    if (mod && loadedSec.indexOf(mod.base) === -1) {
        loadedSec.push(mod.base);
        console.log('[bypass] >>> 安全库已加载，检测从这里开始生效');
    }

    if (ticks >= 18) clearInterval(timer);
}, 10000);