/**
 * db_spawn_bypass.js — 豆瓣 spawn 绕过（精简可用版）
 *
 * 已验证有效的部分：
 *   1. patch libmsaoaidsec.so + 0x1AF20  →  TracerPid 检查永真返回 0
 *   2. 拦 libnesec/msaoa 发起的 munmap/dlclose（保住 agent）
 *
 * 注意：不要 hook exit/_exit（会拖死 frida 的 JS 线程，setInterval 全部饿死），
 *      也不要 hook strstr（启动期调用量太大）。
 *
 * 配合 florida-server 使用；官方 frida-server 会在 agent 层面被识别。
 *
 * 用法：
 *   frida -Uf com.douban.frodo -l db_spawn_bypass.js
 */

'use strict';

var MODULE = 'libmsaoaidsec.so';
var OFF_TRACERPID = 0x1AF20;
var SEC_LIB = /msaoa|nesec|secexe/i;

var base = null;
var s = { patched: 0, memBlocked: 0, dlBlocked: 0, ticks: 0 };

function log(m) { console.log('[db] ' + m); }

/* ---------- 1. patch TracerPid 检查 ---------- */

function tryPatch() {
    if (base) return;
    var b = null;
    try { b = Module.findBaseAddress(MODULE); } catch (e) { return; }
    if (!b) return;

    base = b;
    log('FOUND ' + MODULE + ' base=' + b);
    try {
        Interceptor.replace(b.add(OFF_TRACERPID), new NativeCallback(function () {
            return 0;                       // 永远「没人 ptrace 我」
        }, 'int64', []));
        s.patched = 1;
        log('PATCHED +0x' + OFF_TRACERPID.toString(16));
    } catch (e) {
        log('patch failed: ' + e);
    }
}

/* ---------- 2. 拦住安全库的内存/卸载操作 ---------- */

function secCaller(ra) {
    var m = Process.findModuleByAddress(ra);
    return (m && SEC_LIB.test(m.name)) ? m.name : null;
}

var munmap = Module.findExportByName(null, 'munmap');
if (munmap) {
    Interceptor.attach(munmap, {
        onEnter: function (a) {
            if (!secCaller(this.returnAddress)) return;
            this.block = true;
            s.memBlocked++;
            log('BLOCK munmap(0x' + a[1].toUInt32().toString(16) + ')');
        },
        onLeave: function (r) { if (this.block) r.replace(ptr(-1)); }
    });
}

var dlclose = Module.findExportByName(null, 'dlclose');
if (dlclose) {
    Interceptor.attach(dlclose, {
        onEnter: function (a) {
            if (!secCaller(this.returnAddress)) return;
            this.block = true;
            s.dlBlocked++;
            log('BLOCK dlclose');
        },
        onLeave: function (r) { if (this.block) r.replace(ptr(0)); }
    });
}

/* ---------- 3. 心跳 + 定时 patch ---------- */

setInterval(function () {
    s.ticks++;
    tryPatch();
    if (s.ticks % 10 === 0) {
        log('stats: patch=' + s.patched + ' mem=' + s.memBlocked +
            ' dl=' + s.dlBlocked + ' mod=' + (base ? 'yes' : 'no'));
    }
}, 1000);

log('ready');
