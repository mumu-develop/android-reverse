'use strict';
/* libs.js —— 观察 so 加载顺序，替代 21-hookopen.js
 *
 * 为什么不用 hook dlopen：
 *   dlopen/android_dlopen_ext 在 spawn 阶段处于 linker 内部临界区，
 *   Interceptor 挂上去要分配 trampoline + 解析符号，可能再次进 dlopen，
 *   造成自锁 —— 表现为 frida 不报错、日志 0 字节、APP 画面卡住。
 * 改成轮询 Process.enumerateModules() 做差集：不进 linker、不会死锁。
 *
 * 用法：frida -Uf com.xingin.xhs -l xhs_bypass.js -l libs.js
 */

var INTERVAL_MS = 500;
var MAX_TICKS = 240;          // 120 秒后停
var FILTER = null;            // 例如 /xhs|xyass|shield|msaoai/i

var seen = {};
Process.enumerateModules().forEach(function (m) { seen[m.name] = m.base.toString(); });
console.log('[libs] baseline=' + Object.keys(seen).length + ' modules');

var tick = 0;
var timer = setInterval(function () {
    tick++;
    var list;
    try { list = Process.enumerateModules(); } catch (e) { clearInterval(timer); return; }
    list.forEach(function (m) {
        if (seen[m.name] === m.base.toString()) return;
        seen[m.name] = m.base.toString();
        if (FILTER && !FILTER.test(m.name)) return;
        console.log('[load] ' + m.name + '  base=' + m.base + '  size=0x' + m.size.toString(16) +
            '  ' + m.path);
    });
    if (tick >= MAX_TICKS) {
        clearInterval(timer);
        console.log('[libs] stop, total=' + Object.keys(seen).length);
    }
}, INTERVAL_MS);

// 想立刻看当前全量：在 frida REPL 里敲 dump()  或脚本里调 dump()
global.dump = function (pat) {
    var re = pat ? new RegExp(pat, 'i') : null;
    Process.enumerateModules().forEach(function (m) {
        if (re && !re.test(m.name)) return;
        console.log(m.name + '  ' + m.base + '  0x' + m.size.toString(16) + '  ' + m.path);
    });
};
