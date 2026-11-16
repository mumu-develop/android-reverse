/**
 * thread_kill_generic.js — 通用版：任何关注模块起的线程，入口一律变成「立即返回」
 *
 * 核心：在 pthread_create 的 onEnter 里改 —— 此时线程还没被创建，
 *       改完再让它创建，线程一启动就 return。不需要知道任何偏移。
 *
 * 用 Memory.patchCode 直接写 `31 c0 c3`（x86_64: xor eax,eax; ret），
 * 不装 trampoline，因此可以安全地在回调里同步执行。
 */
'use strict';

var WATCH = /msaoa|nesec|secexe|yidun/i;
var STUB = [0x31, 0xc0, 0xc3];
var T0 = Date.now();
var n = 0, patched = 0;

function log(m) { console.log('[' + (Date.now() - T0) + 'ms] ' + m); }

function hex(p, k) {
    try {
        var b = new Uint8Array(Memory.readByteArray(p, k || 8)), s = '';
        for (var i = 0; i < b.length; i++) s += ('0' + b[i].toString(16)).slice(-2) + ' ';
        return s;
    } catch (e) { return 'unreadable'; }
}

var pth = Module.findExportByName(null, 'pthread_create');
if (!pth) { log('! no pthread_create'); }

Interceptor.attach(pth, {
    onEnter: function (a) {
        n++;
        var entry = a[2];
        var m = null;
        try { m = Process.findModuleByAddress(entry); } catch (e) { return; }
        if (!m || !WATCH.test(m.name)) return;

        var off = entry.sub(m.base);
        var key = m.name + '+0x' + off.toString(16);
        log('thread entry ' + key + '  before: ' + hex(entry));

        try {
            Memory.patchCode(entry, 3, function (code) { code.writeByteArray(STUB); });
            patched++;
            log('  -> stubbed, after: ' + hex(entry));
        } catch (e) {
            log('  FAILED: ' + e);
        }
    }
});

setInterval(function () {
    log('alive  threads=' + n + '  stubbed=' + patched);
}, 2000);

log('ready');
