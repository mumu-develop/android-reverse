'use strict';
/* trap.js —— 定位"闪退到底是谁干的"
 *
 * 解决的问题：21-hookopen.js 靠 hook dlopen 看 so 加载，会在 spawn 阶段
 *             自锁 linker -> zygote 卡在 tracing stop -> 整机卡死。
 *
 * 这里改用两条互不干扰的线：
 *   A) 轮询 Process.enumerateModules() 做差集，记录每个 so 的加载时刻（不进 linker）
 *   B) hook 所有退出点和崩溃点，打印原生调用栈（模块名+偏移）
 *
 * 读日志的方法：
 *   - 最后一条 [LOAD]  = 闪退前最后加载的 so
 *   - [EXIT] 后面那行栈 = 真正调用 exit 的模块和偏移（这才是凶手）
 *   - [CRASH]          = 真信号崩溃，addr 落在哪个模块就是哪个 so
 *
 * 用法（spawn，不 hook dlopen，所以不会卡）：
 *   frida -Uf com.xingin.xhs -l trap.js
 * 用法（attach，先手动开 app）：
 *   frida -U -n com.xingin.xhs -l trap.js
 */

var T0 = Date.now();
var POLL_MS = 50;

/* 开关 —— 实测：spawn 阶段装 setExceptionHandler 会把 ART 自己的 SIGSEGV
 * 处理链打乱（曾把进程在 +68ms 直接干掉，栈落在 libunwindstack），
 * 所以默认关掉。真需要抓 SIGSEGV 时改成 true，并用 attach 模式跑。 */
var USE_EXC_HANDLER = false;
/* Java 侧 hook 延迟安装：spawn 瞬间就替换 System.exit/Runtime.halt 容易踩到
 * ART 早期初始化，延迟 800ms 更稳。 */
var JAVA_DELAY_MS = 800;

function ts() {
    var d = Date.now() - T0;
    return '+' + (d < 10000 ? '0' + d : d) + 'ms';
}
function log(s) { console.log(ts() + ' ' + s); }

function sym(a) {
    var m = Process.findModuleByAddress(a);
    return m ? (m.name + '+0x' + a.sub(m.base).toString(16)) : a.toString();
}

function bt(ctx, n) {
    try {
        return Thread.backtrace(ctx, Backtracer.FUZZY).slice(0, n || 12)
            .map(sym).join('\n              <- ');
    } catch (e) { return '(no backtrace: ' + e + ')'; }
}

/* ---------------- A. so 加载时间线 ---------------- */

var seen = {};
Process.enumerateModules().forEach(function (m) { seen[m.name] = true; });
log('[trap] baseline = ' + Object.keys(seen).length + ' modules');

var loading = 0;
setInterval(function () {
    if (loading) return;
    loading = 1;
    try {
        var list = Process.enumerateModules();
        for (var i = 0; i < list.length; i++) {
            var m = list[i];
            if (seen[m.name]) continue;
            seen[m.name] = true;
            log('[LOAD ] ' + m.name + '  size=0x' + m.size.toString(16) + '  ' + m.path);
        }
    } catch (e) { }
    loading = 0;
}, POLL_MS);

/* ---------------- B. 谁在退出 ---------------- */

function hookExit(name, withCode) {
    var p = Module.findExportByName(null, name);
    if (!p) { log('[trap] ' + name + ' not found'); return; }
    Interceptor.attach(p, {
        onEnter: function (args) {
            log('[EXIT ] ' + name + '(' + (withCode ? args[0].toInt32() : '') + ')  <-- killer stack:');
            log('        ' + bt(this.context, 12));
        }
    });
    log('[trap] hooked ' + name);
}

/* 注意：不要挂 pthread_exit —— 每个 Java 线程正常结束都会走它，
 * 日志会被几十条 "[EXIT] pthread_exit()" 噪音刷满，且 hook 它本身有风险。 */
['exit', '_exit', '_Exit', 'abort', 'raise'].forEach(function (n) {
    hookExit(n, true);
});

/* ---------------- C. 真崩溃 ---------------- */

if (USE_EXC_HANDLER) {
    Process.setExceptionHandler(function (d) {
        log('[CRASH] ' + d.type + '  addr=' + d.address + '  (' + sym(d.address) + ')');
        log('        ' + bt(d.context, 14));
        return false;   // 不吞掉，让进程照常死，方便看系统日志
    });
    log('[trap] exception handler ON');
} else {
    log('[trap] exception handler OFF (见文件头注释)');
}

/* ---------------- D. Java 侧退出 ---------------- */

function javaStack() {
    try {
        console.log(Java.use('android.util.Log').getStackTraceString(
            Java.use('java.lang.Throwable').$new()));
    } catch (e) { }
}

setTimeout(function () { Java.perform(function () {
    try {
        var Sys = Java.use('java.lang.System');
        Sys.exit.implementation = function (code) {
            log('[JAVA ] System.exit(' + code + ')');
            javaStack();
            this.exit(code);
        };
        log('[trap] hooked System.exit');
    } catch (e) { log('[trap] System.exit: ' + e); }

    try {
        var Proc = Java.use('android.os.Process');
        Proc.killProcess.implementation = function (pid) {
            log('[JAVA ] Process.killProcess(' + pid + ')');
            javaStack();
            return this.killProcess(pid);
        };
        log('[trap] hooked Process.killProcess');
    } catch (e) { log('[trap] killProcess: ' + e); }

    try {
        var Rt = Java.use('java.lang.Runtime');
        Rt.halt.implementation = function (code) {
            log('[JAVA ] Runtime.halt(' + code + ')');
            javaStack();
            this.halt(code);
        };
        log('[trap] hooked Runtime.halt');
    } catch (e) { log('[trap] Runtime.halt: ' + e); }
}); }, JAVA_DELAY_MS);

/* ---------------- E. REPL 手动命令 ---------------- */

global.mods = function (pat) {
    var re = pat ? new RegExp(pat, 'i') : null;
    Process.enumerateModules().forEach(function (m) {
        if (re && !re.test(m.name)) return;
        console.log(m.name + '  ' + m.base + '  0x' + m.size.toString(16));
    });
};
