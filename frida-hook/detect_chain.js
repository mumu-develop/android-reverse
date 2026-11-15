/**
 * detect_chain.js — 检测链路追踪（稳定版）
 *
 * 为什么会在真机上卡死（锁环，概率性触发）：
 *   脚本挂了 open/openat 的钩子；linker 在 dlopen 内部正好要调 open 打开 .so。
 *   线程B 在 dlopen 里持 linker 锁 → 调 open → 命中钩子 → 等 JS 锁；
 *   线程A 已在钩子里持 JS 锁 → 调 findModuleByAddress → 等 linker 锁。→ 互等，进程停住。
 *   所以本脚本不挂 open/openat，只挂 fopen/lstat/readlink（linker 不用这三个）。
 *
 * 三次踩的雷，别再碰：
 *   1. Process.enumerateRanges() / enumerateModules() 内部会读 /proc/self/maps，
 *      而 open/fopen 被我们挂着 → JS 线程重入钩子 → 申请自己已持有的 JS 锁 → 死锁。
 *      在 JS 里打标志拦不住，因为重入发生在进入 JS 之前。
 *   2. Process.findModuleByName() 在 dlopen 进行中调用，会等 linker 锁 → 同样卡死。
 *   3. 在钩子里丢 this（写成 fn(a) 而不是 fn.call(this, a)）→ 每次调用都抛异常，
 *      异常构造开销把进程拖死。
 *
 * 这一版的取舍：
 *   - 钩子里只用 Process.findModuleByAddress()（读 Frida 缓存，不碰文件、不等 linker）
 *   - 只用 ACCURATE 回溯，不用 FUZZY（快，且不会有假帧）
 *   - 每个调用点只展开一次链，其余只计数
 *
 * 用法：frida -Uf <pkg> -l detect_chain.js
 */
'use strict';

var WATCH_MOD = /msaoa|nesec|secexe|yidun/i;
var PROC_RE = /^\/proc\/(self|\d+)\//;
var DEPTH = 6;
var INLINE_FRAMES = 3;

var T0 = Date.now();
var shown = {}, counts = { load: 0, thread: 0, read: 0, hit: 0 };

function ts() { return ('     ' + (Date.now() - T0)).slice(-6); }
function tid() { var n = Process.getCurrentThreadId(); return ('     ' + n).slice(-6); }

function where(a) {
    try {
        var m = Process.findModuleByAddress(a);
        return m ? (m.name + '+0x' + a.sub(m.base).toString(16)) : null;
    } catch (e) { return null; }
}

function chain(ctx) {
    var out = [], seen = {};
    var bt = [];
    try { bt = Thread.backtrace(ctx, Backtracer.ACCURATE); } catch (e) { }
    for (var i = 0; i < bt.length && out.length < DEPTH; i++) {
        var s = where(bt[i]);
        if (!s) break;                 // 解析不出模块就停，后面都是野栈
        if (seen[s]) continue;
        seen[s] = 1;
        out.push(s);
    }
    return out;
}

function chainText(fr) {
    if (!fr.length) return '';
    if (fr.length <= INLINE_FRAMES) return fr.join(' > ');
    return fr.slice(0, INLINE_FRAMES).join(' > ') + ' ..+' + (fr.length - INLINE_FRAMES);
}

function once(k) {
    if (shown[k]) return false;
    shown[k] = 1;
    return true;
}

/* ---------- dlopen ---------- */
var dl = Module.findExportByName(null, 'android_dlopen_ext') ||
         Module.findExportByName(null, 'dlopen');
if (dl) {
    Interceptor.attach(dl, {
        onEnter: function (a) {
            var p = a[0];
            if (p.isNull()) return;
            var s = null;
            try { s = p.readCString(); } catch (e) { return; }
            if (!s || !/^\/data\//.test(s) || !/\.so$/.test(s)) return;
            counts.load++;
            console.log('[' + ts() + '] ' + tid() + '  LOAD   #' + counts.load + ' ' + s.split('/').pop());
        }
    });
}

/* ---------- pthread_create ---------- */
var pth = Module.findExportByName(null, 'pthread_create');
if (pth) {
    Interceptor.attach(pth, {
        onEnter: function (a) {
            var w = where(a[2]);
            if (!w) return;
            var name = w.split('+')[0];
            if (!WATCH_MOD.test(name)) return;
            counts.thread++;
            if (!once('thr|' + w)) return;
            console.log('[' + ts() + '] ' + tid() + '  THREAD entry ' + w +
                '   creator ' + (where(this.returnAddress) || '?'));
        }
    });
}

/* ---------- /proc 访问 ---------- */
function hookPath(name, argi) {
    var f = Module.findExportByName(null, name);
    if (!f) return;
    Interceptor.attach(f, {
        onEnter: function (a) {
            var s = null;
            try { s = a[argi].readCString(); } catch (e) { return; }
            if (!s || !PROC_RE.test(s)) return;

            var w = where(this.returnAddress);      // 唯一一次 Frida 查询
            if (!w) return;
            var mn = w.split('+')[0];
            if (/^libc\.so$/.test(mn)) return;      // libc 内部转发

            counts.read++;
            var norm = s.replace(/\/\.\.?$/, '').replace(/\d+/g, '#');
            if (!once('r|' + name + '|' + norm + '|' + w)) return;

            var fr = chain(this.context);
            console.log('[' + ts() + '] ' + tid() + '  READ   ' + name + '("' + s + '")' +
                (fr.length ? '   ' + chainText(fr) : ''));
        }
    });
}

hookPath('fopen', 0);
/* open/openat 不挂：linker 在 dlopen 内部就调它们，会形成锁环（见文件头） */
hookPath('lstat', 0);
hookPath('readlink', 0);
hookPath('readlinkat', 1);

/* ---------- 终结动作 ---------- */
['_exit', 'exit', 'abort', 'dlclose'].forEach(function (n) {
    var f = Module.findExportByName(null, n);
    if (!f) return;
    Interceptor.attach(f, {
        onEnter: function () {
            var w = where(this.returnAddress);
            if (!w || /^libc\.so/.test(w)) return;
            counts.hit++;
            console.log('[' + ts() + '] ' + tid() + '  HIT    ' + n);
            var fr = chain(this.context);
            for (var i = 0; i < fr.length; i++) {
                console.log('                          ' + (i === 0 ? '<- ' : '   ') + fr[i]);
            }
        }
    });
});

['kill', 'tgkill'].forEach(function (n) {
    var f = Module.findExportByName(null, n);
    if (!f) return;
    Interceptor.attach(f, {
        onEnter: function () {
            var w = where(this.returnAddress);
            if (!w || /^libc\.so/.test(w)) return;
            counts.hit++;
            console.log('[' + ts() + '] ' + tid() + '  HIT    ' + n);
            var fr = chain(this.context);
            for (var i = 0; i < fr.length; i++) {
                console.log('                          ' + (i === 0 ? '<- ' : '   ') + fr[i]);
            }
        }
    });
});

setInterval(function () {
    console.log('[' + ts() + '] ---- alive  load=' + counts.load + ' thread=' + counts.thread +
        ' read=' + counts.read + ' hit=' + counts.hit);
}, 3000);

console.log('[' + ts() + '] ready   READ=inline  HIT=full chain');
