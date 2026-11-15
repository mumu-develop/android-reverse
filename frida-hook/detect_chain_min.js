/**
 * detect_chain_min.js — 不会卡死的检测链路追踪
 *
 * 实测结论（这台机器上验证过）：
 *   在 fopen 的钩子里调用 Process.findModuleByAddress 会把进程锁死。
 *   原因：msaoa 的构造函数里就调 fopen("/proc/<pid>/cmdline")，而构造函数在
 *   dlopen 内部执行、当前线程持有 linker 锁；findModuleByAddress 又要这把锁
 *   → 同一个线程把自己锁死（不需要两个线程）。
 *
 * 对照实验：
 *   空脚本                → 正常进首页
 *   fopen 钩子只 n++      → 正常进首页（24s 仅 101 次调用）
 *   fopen 钩子调 findModuleByAddress → 卡死在闪屏
 *
 * 本脚本的规矩：
 *   钩子里只做 readU16 两字节过滤 + 记原始地址，绝不碰 Frida 的模块 API
 *   模块名延迟解析：等「最近 3 秒没有 dlopen」了，再从定时器里查
 *
 * 用法：frida -q -Uf <pkg> -l detect_chain_min.js
 */
'use strict';

var T0 = Date.now();
var lastDlopen = 0;      // 最近一次 dlopen 时间戳
var pending = {};        // ra 字符串 -> 已解析
var queue = [];          // 待解析的 ra
var n = { load: 0, thread: 0, read: 0, hit: 0 };

function ts() { return ('     ' + (Date.now() - T0)).slice(-6); }
function tid() { var v = Process.getCurrentThreadId(); return ('     ' + v).slice(-6); }

/* 每秒最多打 6 条，热路径直接丢，避免刷屏把 app 拖慢 */
var budget = 0;
setInterval(function () { budget = 0; }, 1000);

function cheapPrint(line) {
    if (budget >= 6) return;
    budget++;
    console.log(line);
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
            n.load++;
            lastDlopen = Date.now();
            console.log('[' + ts() + '] ' + tid() + '  LOAD   #' + n.load + ' ' + s.split('/').pop());
        }
    });
}

/* ---------- pthread_create ---------- */
var pth = Module.findExportByName(null, 'pthread_create');
if (pth) {
    Interceptor.attach(pth, {
        onEnter: function (a) {
            n.thread++;
            if (n.thread > 40) return;
            var raS = this.returnAddress.toString();
            if (!pending[raS]) { pending[raS] = 0; queue.push(raS); }
            console.log('[' + ts() + '] ' + tid() + '  THREAD entry ra=' + a[2] +
                '   creator ra=' + raS);
        }
    });
}

/* ---------- /proc 访问：只记地址 ---------- */
function hookPath(name, argi) {
    var f = Module.findExportByName(null, name);
    if (!f) return;
    Interceptor.attach(f, {
        onEnter: function (a) {
            var u = 0;
            try { u = a[argi].readU16(); } catch (e) { return; }   // 纯数字比较
            if (u !== 0x702F) return;                              // 不是 "/p"

            n.read++;
            if (budget >= 6) return;

            var s = null;
            try { s = a[argi].readCString(); } catch (e) { return; }
            if (!s || s.indexOf('/proc/') !== 0) return;

            var raS = this.returnAddress.toString();
            if (!pending[raS]) { pending[raS] = 0; queue.push(raS); }
            cheapPrint('[' + ts() + '] ' + tid() + '  READ   ' + name + '("' + s + '")   ra=' + raS);
        }
    });
}

hookPath('fopen', 0);
hookPath('lstat', 0);
hookPath('readlink', 0);
hookPath('readlinkat', 1);

/* ---------- 终结动作 ---------- */
['_exit', 'exit', 'abort', 'dlclose', 'kill', 'tgkill'].forEach(function (name) {
    var f = Module.findExportByName(null, name);
    if (!f) return;
    Interceptor.attach(f, {
        onEnter: function () {
            n.hit++;
            if (n.hit > 60) return;
            var raS = this.returnAddress.toString();
            if (!pending[raS]) { pending[raS] = 0; queue.push(raS); }
            console.log('[' + ts() + '] ' + tid() + '  HIT    ' + name + '   ra=' + raS);
        }
    });
});

/* ---------- 延迟解析：dlopen 安静 3 秒后才查模块 ---------- */
setInterval(function () {
    if (Date.now() - lastDlopen < 3000) return;   // 有人正在 dlopen，别碰
    var done = 0;
    while (queue.length && done < 8) {
        var raS = queue.shift();
        if (pending[raS]) continue;
        pending[raS] = 1;
        try {
            var p = ptr(raS);
            var m = Process.findModuleByAddress(p);
            if (m) console.log('[map] ' + raS + ' -> ' + m.name + '+0x' + p.sub(m.base).toString(16));
            else console.log('[map] ' + raS + ' -> ?');
        } catch (e) { }
        done++;
    }
}, 3000);

setInterval(function () {
    console.log('[' + ts() + '] ---- alive  load=' + n.load + ' thread=' + n.thread +
        ' read=' + n.read + ' hit=' + n.hit + '  pid=' + Process.id + '  queue=' + queue.length);
}, 3000);

console.log('[' + ts() + '] ready  pid=' + Process.id);
