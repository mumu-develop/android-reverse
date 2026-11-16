/**
 * xhs_hook_params.js —— 抓接口参数 / 请求头，并打印堆栈定位来源类
 * ================================================================
 * 依赖：Java 桥（Java.perform）。必须先让 bypass 生效且 Java 桥不被杀。
 *
 * 抓取点（全部来自静态分析已定位的类）：
 *   kfc.a.b(gec.a, Request)         → 拼好的 xy-common-params 字符串
 *   nud.e$c(Request)                → header 名 → 取值 lambda 的 HashMap
 *   nud.e$a.a()                     → 同上（无参入口）
 *   okhttp3.Request$Builder.addHeader / header
 *                                   → 所有实际写入的请求头（含 shield / x-mini-* / xy-*）
 *   nud.u.intercept                 → xy-direction 拦截器
 *   nud.x.intercept                 → xy-scene 拦截器
 *   iad.p.a(chain, request, map)    → x-legacy-* / tiny 签名拦截器
 *
 * 每条输出都带「调用者堆栈」，可直接定位到生成这些值的类。
 *
 * 用法：
 *   frida -Uf com.xingin.xhs -l xhs_bypass.js -l xhs_hook_params.js
 *   或先起 App 再 attach：
 *   frida -U -n com.xingin.xhs -l xhs_hook_params.js
 */

'use strict';

var CFG = {
    showStack: true,       // 是否打印堆栈
    stackDepth: 10,        // 堆栈保留层数
    // 只关心这些头（全部记录会淹没输出）
    headerFilter: ['shield', 'xy-', 'x-mini', 'x-legacy', 'x-s', 'x-t', 'x-b3', 'x-xray'],
    maxPerKey: 3           // 每个抓取点最多打印几次，避免刷屏
};

var counters = {};
function budget(key) {
    counters[key] = (counters[key] || 0) + 1;
    return counters[key] <= CFG.maxPerKey;
}

function log(tag, msg) {
    console.log('\n===== ' + tag + ' =====\n' + msg);
}

/** 取当前 Java 调用栈（跳过前几层 frida 自己的帧） */
function stack(depth) {
    if (!CFG.showStack) return '';
    depth = depth || CFG.stackDepth;
    try {
        var Thread = Java.use('java.lang.Thread');
        var st = Thread.currentThread().getStackTrace();
        var out = [];
        var skipped = 0;
        for (var i = 0; i < st.length && out.length < depth; i++) {
            var s = String(st[i]);
            // 跳过 frida 桥自身的帧
            if (s.indexOf('com.frida.') !== -1 || s.indexOf('re.frida') !== -1) continue;
            if (skipped < 2 && s.indexOf('java.lang.Thread') !== -1) { skipped++; continue; }
            out.push('    at ' + s);
        }
        return out.join('\n');
    } catch (e) {
        return '    <取堆栈失败: ' + e + '>';
    }
}

/** 把 Java Map 转成可读文本 */
function dumpMap(map) {
    try {
        var iter = map.entrySet().iterator();
        var lines = [];
        var n = 0;
        while (iter.hasNext() && n < 200) {
            var e = iter.next();
            var k = String(e.getKey());
            var v = e.getValue();
            var vs;
            try { vs = String(v); } catch (err) { vs = '<' + err + '>'; }
            // lambda 的 toString 是类名，这里标注一下
            lines.push('    ' + k + ' = ' + vs);
            n++;
        }
        return lines.join('\n');
    } catch (e) {
        return '    <dumpMap 失败: ' + e + '>';
    }
}

function interested(name) {
    var n = String(name).toLowerCase();
    for (var i = 0; i < CFG.headerFilter.length; i++) {
        if (n.indexOf(CFG.headerFilter[i]) === 0 || n === CFG.headerFilter[i]) return true;
    }
    return false;
}

Java.perform(function () {
    console.log('[hook] Java 桥就绪，开始挂钩');

    /* ---------- 1. xy-common-params 的最终字符串 ---------- */
    try {
        var KfcA = Java.use('kfc.a');
        KfcA.b.overload('gec.a', 'okhttp3.Request').implementation = function (provider, req) {
            var url = '';
            try { url = String(req.url().toString()); } catch (e) { }
            var ret = this.b(provider, req);
            if (budget('kfc.a.b')) {
                log('kfc.a.b → xy-common-params',
                    'URL: ' + url + '\n' +
                    '返回字符串(' + String(ret).length + ' 字符):\n    ' + ret + '\n' +
                    '堆栈:\n' + stack());
            }
            return ret;
        };
        console.log('[hook] kfc.a.b ✔');
    } catch (e) {
        console.log('[hook] kfc.a.b 失败: ' + e);
    }

    /* ---------- 2. header 名 → 取值 lambda 的 HashMap ---------- */
    try {
        var Ea = Java.use('nud.e$a');
        Ea.a.overload().implementation = function () {
            var ret = this.a();
            if (budget('nud.e$a.a')) {
                log('nud.e$a.a → header 提供者 map',
                    '条目数: ' + ret.size() + '\n' +
                    dumpMap(ret) + '\n' +
                    '堆栈:\n' + stack());
            }
            return ret;
        };
        console.log('[hook] nud.e$a.a ✔');
    } catch (e) {
        console.log('[hook] nud.e$a.a 失败: ' + e);
    }

    /* ---------- 3. 实际写入的每个请求头（最关键） ---------- */
    try {
        var B = Java.use('okhttp3.Request$Builder');
        ['addHeader', 'header'].forEach(function (method) {
            try {
                B[method].overload('java.lang.String', 'java.lang.String').implementation = function (name, value) {
                    try {
                        if (interested(name) && budget('hdr:' + name)) {
                            var url = '';
                            try { url = String(this.build().url().toString()); } catch (e) { }
                            log('请求头 ' + name,
                                '值: ' + value + '\n' +
                                'URL: ' + url + '\n' +
                                '堆栈:\n' + stack());
                        }
                    } catch (e) { }
                    return B[method].overload('java.lang.String', 'java.lang.String')
                        .call(this, name, value);
                };
                console.log('[hook] Request$Builder.' + method + ' ✔');
            } catch (e) {
                console.log('[hook] Request$Builder.' + method + ' 失败: ' + e);
            }
        });
    } catch (e) {
        console.log('[hook] Request$Builder 失败: ' + e);
    }

    /* ---------- 4. 各拦截器 ---------- */
    function hookInterceptor(cls, label) {
        try {
            var C = Java.use(cls);
            C.intercept.overload('okhttp3.Interceptor$Chain').implementation = function (chain) {
                var url = '';
                try { url = String(chain.request().url().toString()); } catch (e) { }
                var ret = this.intercept(chain);
                if (budget('itc:' + cls)) {
                    var hdrs = '';
                    try {
                        var req = chain.request();
                        hdrs = '请求头: ' + String(req.headers());
                    } catch (e) { }
                    log(label + ' (' + cls + ')',
                        'URL: ' + url + '\n' + hdrs + '\n堆栈:\n' + stack());
                }
                return ret;
            };
            console.log('[hook] ' + cls + ' ✔');
        } catch (e) {
            console.log('[hook] ' + cls + ' 失败: ' + e);
        }
    }
    hookInterceptor('nud.u', 'xy-direction 拦截器');
    hookInterceptor('nud.x', 'xy-scene 拦截器');

    /* ---------- 5. tiny 签名拦截器 ---------- */
    try {
        var P = Java.use('iad.p');
        P.a.overload('okhttp3.Interceptor$Chain', 'okhttp3.Request', 'java.util.Map').implementation = function (chain, req, map) {
            if (budget('iad.p.a')) {
                var url = '';
                try { url = String(req.url().toString()); } catch (e) { }
                log('iad.p.a → x-legacy-* / tiny 签名',
                    'URL: ' + url + '\n' +
                    '传入 map:\n' + dumpMap(map) + '\n' +
                    '堆栈:\n' + stack());
            }
            return this.a(chain, req, map);
        };
        console.log('[hook] iad.p.a ✔');
    } catch (e) {
        console.log('[hook] iad.p.a 失败: ' + e);
    }

    console.log('[hook] 全部挂钩完成，去 App 里刷新一次');
});

setInterval(function () {
    var s = [];
    for (var k in counters) s.push(k + '=' + counters[k]);
    console.log('[hook] 统计: ' + (s.length ? s.join(' ') : '还没有命中'));
}, 30000);
