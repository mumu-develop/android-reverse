/**
 * so_killer.js — 只回答一个问题：哪个 so 让 frida 挂掉
 *
 * 两种模式：
 *   watch  只观察：打印私有 so 的加载、死前的敏感读取、杀进程动作
 *   block  拦截：把命中的 so 直接拦掉（dlopen 返回 0），app 活了就说明是它
 *
 * 设计约束（都是踩过的坑）：
 *   - 不 hook dlopen，只 hook android_dlopen_ext（hook dlopen 会让 Frida 自己 abort）
 *   - 钩子里不调用任何 Frida 模块 API（会在 dlopen 期间自锁）
 *   - 热路径只用 readU16 判断前缀，不算字符串
 *
 * 用法：
 *   frida -q -Uf <pkg> -l so_killer.js
 *   改下面的 MODE / BLOCK 再跑
 */
'use strict';

/* ================= 配置 ================= */

var MODE = 'watch';                     // 'watch' 或 'block'
var BLOCK = /msaoaidsec|nesec|secexe/i; // block 模式：命中这些就掐掉

var PROC_RE = /^\/(proc|lstat|readlink)/;   // 仅用于注释，实际用字节过滤

/* ================= 基础 ================= */

var T0 = Date.now();
var n = { load: 0, blocked: 0, read: 0, hit: 0 };
var seenRa = {};      // 同一个读取点只报一次

function ts() { return ('     ' + (Date.now() - T0)).slice(-6); }
function tid() { var v = Process.getCurrentThreadId(); return ('     ' + v).slice(-6); }
function tag() { return '[' + ts() + ']'; }

/* 每秒限流，热路径直接丢 */
var budget = 0;
setInterval(function () { budget = 0; }, 1000);
function say(line) {
    if (budget >= 8) return;
    budget++;
    console.log(line);
}

/* ================= 1. so 加载（唯一入口） ================= */

var ext = Module.findExportByName(null, 'android_dlopen_ext');
if (ext) {
    Interceptor.attach(ext, {
        onEnter: function (a) {
            var p = a[0];
            this.skip = true;
            if (p.isNull()) return;
            var s = null;
            try { s = p.readCString(); } catch (e) { return; }
            if (!s) return;
            // 只看 App 自己的私有 so；系统库全忽略
            if (s.indexOf('/data/') !== 0) return;
            if (!/\.so$/.test(s)) return;

            this.skip = false;
            this.name = s.split('/').pop();
            this.path = s;

            // block 模式必须在 onEnter 动手：构造函数是在 dlopen 内部跑完的，
            // onLeave 再返回 0 已经晚了（检测已经注册好了）。
            // 手段：把路径首字节改成 0，变成空串 → dlopen 找不到文件 → 直接失败。
            if (MODE === 'block' && BLOCK.test(s)) {
                try {
                    this.mutePtr = p;
                    this.muteOrig = p.readU8();
                    p.writeU8(0);
                    this.muted = true;
                } catch (e) {
                    console.log(tag() + ' ! 路径只读，拦不住 ' + this.name);
                }
            }

            n.load++;
            console.log(tag() + ' ' + tid() + '  LOAD   ' + this.name +
                '   (#' + n.load + ' private so)' + (this.muted ? '   [将拦掉]' : ''));
        },
        onLeave: function (ret) {
            if (this.muted) {
                try { this.mutePtr.writeU8(this.muteOrig); } catch (e) { }
                n.blocked++;
                console.log(tag() + ' ' + tid() + '  BLOCK  ' + this.name +
                    ' → 已被拦（返回 ' + ret + '）');
            }
        }
    });
} else {
    console.log(tag() + ' ! 找不到 android_dlopen_ext');
}

/* ================= 2. 死前动作：杀/卸 ================= */

['_exit', 'exit', 'abort', 'kill', 'tgkill', 'dlclose'].forEach(function (name) {
    var f = Module.findExportByName(null, name);
    if (!f) return;
    Interceptor.attach(f, {
        onEnter: function () {
            n.hit++;
            if (n.hit > 40) return;
            console.log(tag() + ' ' + tid() + '  HIT    ' + name +
                '   ra=' + this.returnAddress);
        }
    });
});

/* ================= 3. 敏感读取（只报第一次出现的位置） ================= */

function watchRead(name, argi) {
    var f = Module.findExportByName(null, name);
    if (!f) return;
    Interceptor.attach(f, {
        onEnter: function (a) {
            // 只读 2 字节判断 "/p"：纯数字比较，不分配字符串
            var u = 0;
            try { u = a[argi].readU16(); } catch (e) { return; }
            if (u !== 0x702F) return;

            n.read++;
            var raS = this.returnAddress.toString();
            if (seenRa[raS]) return;          // 同一个点只报一次

            var s = null;
            try { s = a[argi].readCString(); } catch (e) { return; }
            if (!s || s.indexOf('/proc/') !== 0) return;
            seenRa[raS] = 1;

            say(tag() + ' ' + tid() + '  READ   ' + name + '("' + s + '")   ra=' + raS);
        }
    });
}

watchRead('fopen', 0);
watchRead('lstat', 0);
watchRead('readlink', 0);
watchRead('readlinkat', 1);

/* ================= 4. 心跳：看它活到第几秒 ================= */

setInterval(function () {
    console.log(tag() + ' ---- alive  so=' + n.load + ' blocked=' + n.blocked +
        ' read=' + n.read + ' hit=' + n.hit + '  mode=' + MODE);
}, 1000);

console.log(tag() + ' ready  mode=' + MODE + '  pid=' + Process.id);
console.log(tag() + ' 判读方法：最后一条 LOAD 之后的 HIT，就是干你那个 so 的动作');
