/**
 * hook_addr.js — 按「模块 + 偏移」挂 onEnter/onLeave，并打印参数与返回值
 *
 * 特点：
 *   1. 自动等待模块加载（不要求 app 已经跑到那一步）
 *   2. 先判断目标地址是否落在「可执行」页
 *        - 是代码 → Interceptor.attach，打印 x0~x7 / 返回值
 *        - 是数据 → 不 attach（会崩），改成 hex dump 给你看内容
 *   3. 限流：默认最多打印 60 次，防止热函数刷屏把 app 拖死
 *
 * 用法：
 *   frida -q -Uf com.yndaily.wxyd -l hook_addr.js
 *   或 attach：frida -q -U <pid> -l hook_addr.js
 *
 * 改下面三个常量即可。
 */
'use strict';

var MODULE_NAME = 'libwtf.so';   // 目标模块
var OFFSET      = 0xA4C44;       // 目标偏移（十六进制）
var MAX_CALLS   = 60;            // 最多打印多少次

/* ===== 可调 ===== */
var DUMP_ARG_BYTES = 32;         // 每个参数尝试 dump 多少字节
var PRINT_HEX_ARGS = true;       // 参数是否打 hex

/* ============================== */

var T0 = Date.now();
var calls = 0;
var attached = false;

function ts() { return ('     ' + (Date.now() - T0)).slice(-6); }
function tid() { var v = Process.getCurrentThreadId(); return ('     ' + v).slice(-6); }
function log(m) { console.log('[' + ts() + '] ' + m); }

function dumpHex(p, n) {
    try {
        var buf = new Uint8Array(Memory.readByteArray(p, n));
        var hex = [], asc = [];
        for (var i = 0; i < buf.length; i++) {
            hex.push(('0' + buf[i].toString(16)).slice(-2));
            asc.push(buf[i] >= 32 && buf[i] < 127 ? String.fromCharCode(buf[i]) : '.');
        }
        return hex.join(' ') + '   |' + asc.join('') + '|';
    } catch (e) { return '<unreadable>'; }
}

/** 尝试把指针当字符串读（要求落在已映射区、且内容基本可打印） */
function tryString(p) {
    if (!p || p.isNull()) return null;
    var r = null;
    try { r = Process.findRangeByAddress(p); } catch (e) { return null; }
    if (!r || r.protection.indexOf('r') === -1) return null;
    var s = null;
    try { s = p.readCString(64); } catch (e) { return null; }
    if (!s) return null;
    var printable = 0;
    for (var i = 0; i < s.length; i++) {
        var c = s.charCodeAt(i);
        if (c >= 32 && c < 127) printable++;
    }
    if (s.length >= 2 && printable / s.length > 0.85) return s;
    return null;
}

function waitForModule(name, cb, tries) {
    var n = tries === undefined ? 100 : tries;   // 100 * 200ms = 20s
    var b = Module.findBaseAddress(name);
    if (b) { cb(b); return; }
    if (n <= 0) { log('[!] 等不到模块: ' + name); return; }
    setTimeout(function () { waitForModule(name, cb, n - 1); }, 200);
}

waitForModule(MODULE_NAME, function (base) {
    var target = base.add(OFFSET);
    var range = null;
    try { range = Process.findRangeByAddress(target); } catch (e) { }

    log('module  : ' + MODULE_NAME + '  base=' + base);
    log('target  : ' + target + '  (' + MODULE_NAME + '+0x' + OFFSET.toString(16) + ')');
    log('range   : ' + (range ? (range.base + '-' + range.base.add(range.size) + '  ' + range.protection) : '未映射'));

    var isExec = range && range.protection.indexOf('x') !== -1;

    if (!isExec) {
        log('!! 这个地址不在可执行页 —— 不是代码，不能 Interceptor.attach（会破坏数据/崩溃）');
        log('!! 这里给你看它到底是什么内容：');
        for (var k = 0; k < 4; k++) {
            var p = target.add(k * 16);
            log('   ' + p + '  ' + dumpHex(p, 16));
        }
        log('!! 如果想 hook 引用这块数据的函数，用 IDA 的 Xrefs 找到函数起点再改 OFFSET');
        return;
    }

    log('>> attach 到可执行地址');
    attached = true;

    Interceptor.attach(target, {
        onEnter: function (args) {
            calls++;
            if (calls > MAX_CALLS) return;
            var ctx = this.context;
            log('---- #' + calls + ' ENTER  tid=' + tid());

            /* arm64：x0~x7 是前 8 个参数；x86_64 用 rdi/rsi/rdx/rcx/r8/r9 */
            var regs = ['x0', 'x1', 'x2', 'x3', 'x4', 'x5', 'x6', 'x7'];
            for (var i = 0; i < regs.length; i++) {
                var v = ctx[regs[i]];
                if (!v) continue;
                var line = '   ' + regs[i] + ' = ' + v;
                var s = tryString(v);
                if (s) {
                    line += '   "' + s + '"';
                } else if (PRINT_HEX_ARGS && !v.isNull() &&
                           (v.toUInt32() > 0x1000)) {
                    line += '   ' + dumpHex(v, DUMP_ARG_BYTES);
                }
                log(line);
            }
        },
        onLeave: function (retval) {
            if (calls > MAX_CALLS) return;
            var v = retval;
            var line = '---- #' + calls + ' LEAVE  ret = ' + v;
            var s = tryString(v);
            if (s) line += '   "' + s + '"';
            log(line);
        }
    });
});

setInterval(function () {
    log('alive  calls=' + calls + '  attached=' + attached + '  pid=' + Process.id);
}, 5000);
