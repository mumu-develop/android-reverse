// 只 hook libsscronet 的 verify 回调，不碰 android_dlopen_ext
// 规避 metasec 对 dlopen 处 inline hook 的扫描
var target = "SSL_CTX_set_custom_verify";
var libName = "libsscronet.so";
var done = false;

function tryHook() {
    if (done) return;
    var p = Module.findExportByName(libName, target);
    if (p) {
        done = true;
        Interceptor.attach(p, {
            onEnter: function (args) {
                var cb = args[2];
                try {
                    Interceptor.attach(cb, {
                        onLeave: function (retval) {
                            retval.replace(0);
                        }
                    });
                } catch (e) { }
            }
        });
        console.log("[hook] " + libName + "!" + target + " @ " + p);
        return;
    }
    setTimeout(tryHook, 100);
}

setImmediate(tryHook);
