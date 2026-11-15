// hook-appname.js — 枚举 so，打印方法名 + 入参
function wanted(m) {
    if (!/\.so$/i.test(m.name)) return false;
    if (!/^\/data\//.test(m.path)) return false;
    return !/frida|gadget|linjector/i.test(m.name);
}

var done = {};

function scan() {
    Process.enumerateModules().filter(wanted).forEach(function (m) {
        if (done[m.name]) return;
        done[m.name] = 1;
        var fns = m.enumerateSymbols().filter(function (s) {
            return s.type === 'function' && !s.address.isNull();
        });
        console.log('[+] ' + m.name + '  ' + fns.length + ' functions');
        fns.forEach(function (s) {
            try {
                Interceptor.attach(s.address, {
                    onEnter: function (args) {
                        console.log('<' + m.name + '> ' + s.name + ': (' + args.join(', ') + ')');
                    }
                });
            } catch (e) {}
        });
    });
}

setImmediate(scan);
['android_dlopen_ext', 'dlopen'].forEach(function (n) {
    var p = Module.findExportByName(null, n);
    if (p) Interceptor.attach(p, { onLeave: function () { setImmediate(scan); } });
});