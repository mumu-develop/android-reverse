'use strict';
/* hook2.js —— 小红书请求观察（hook.js 的可用版本）
 *
 * hook.js 为什么会闪退，三个原因：
 *   1) showStacks() 从头到尾没有定义 —— 命中条件时抛 ReferenceError，
 *      异常从 Java hook 里冒出去，被 hook 的方法返回 undefined，直接砸崩。
 *   2) hook 了 java.util.HashMap.put（全局热路径，启动期每秒上千次），
 *      每次都要 JS 往返 + 字符串拼日志 —— 主线程被拖死，系统 watchdog 杀进程。
 *   3) hookHeader() 定义了但从来没被调用（Java.use 也在 perform 外面）。
 *
 * 这里改成：只挂 okhttp3.Request$Builder.build()（每请求一次，不在热路径），
 * 一次性把 URL + 全部请求头读出来，按 host 过滤；需要堆栈时打一次。
 *
 * 用法：frida -Uf com.xingin.xhs -l xhs_bypass.js -l hook2.js
 */

var CFG = {
    match: 'xiaohongshu',   // URL 命中这个子串才打印；设 null = 全打
    maxLog: 300,            // 最多打 300 条，防止刷爆
    stacks: ['authorization', 'x-sign', 'x-s', 'shield']  // 头部出现这些时打堆栈
};

var nLog = 0;
var busy = false;

function showStacks(tag) {
    if (busy) return;
    busy = true;
    try {
        var Throwable = Java.use('java.lang.Throwable');
        var Log = Java.use('android.util.Log');
        console.log('\n===== stacks [' + tag + '] =====\n' +
            Log.getStackTraceString(Throwable.$new()));
    } catch (e) {
        console.log('showStacks failed: ' + e);
    }
    busy = false;
}

function install() {
    var Builder;
    try {
        Builder = Java.use('okhttp3.Request$Builder');
    } catch (e) {
        console.log('[hook2] okhttp3 not found yet: ' + e);
        return false;
    }

    Builder.build.implementation = function () {
        var req = this.build();
        try {
            if (req === null || nLog >= CFG.maxLog) return req;
            var url = String(req.url().toString());
            if (CFG.match && url.indexOf(CFG.match) === -1) return req;
            nLog++;
            console.log('\n[' + req.method() + '] ' + url);
            var hs = req.headers();
            var n = hs.size();
            var lower = '\n';
            for (var i = 0; i < n; i++) {
                var k = hs.name(i);
                var v = String(hs.value(i));
                console.log('   ' + k + ': ' + v);
                lower += k.toLowerCase() + '\n';
            }
            for (var j = 0; j < CFG.stacks.length; j++) {
                if (lower.indexOf('\n' + CFG.stacks[j] + '\n') !== -1) {
                    showStacks(CFG.stacks[j]);
                    break;
                }
            }
        } catch (e) {
            console.log('[hook2] dump error: ' + e);
        }
        return req;
    };
    console.log('[hook2] hooked okhttp3.Request$Builder.build');
    return true;
}

Java.perform(function () {
    if (!install()) {
        var t = setInterval(function () { if (install()) clearInterval(t); }, 1000);
    }
});

// 手工开关：REPL 里 rehook() 复位计数
global.rehook = function () { nLog = 0; install(); console.log('[hook2] rearmed'); };
