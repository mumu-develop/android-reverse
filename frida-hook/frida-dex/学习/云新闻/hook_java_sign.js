Java.perform(function () {
    var SM = Java.use("cn.thecover.lib.common.manager.SignManager");

    SM.getSign.overload("java.lang.String", "java.lang.String", "java.lang.String")
        .implementation = function (acc, tok, ts) {
            var ret = this.getSign(acc, tok, ts);
            var tid = Process.getCurrentThreadId();
            console.log("[getSign] tid=" + tid);
            console.log("   account   = " + acc);
            console.log("   token     = '" + tok + "'");
            console.log("   timestamp = " + ts);
            console.log("   => sign   = " + ret);
            return ret;
        };

    console.log("[ready] hooked SignManager.getSign");

    // 自己触发一次，方便确认 hook 生效
    setTimeout(function () {
        try {
            console.log("[trigger] " + SM.getSign("demo-acc", "demo-tok", "1700000000"));
        } catch (e) { console.log("[trigger] err " + e); }
    }, 800);
});
