/*
 * ssl_unpin_safe.js — 保守版 SSL 绕过
 *
 * 和原脚本的区别：
 *   1. 不替换 TrustManager 对象（去掉 registerClass 代理）—— 嫌疑最大的那处
 *   2. 只 hook Conscrypt 的「判定函数」，让它返回空的可信链
 *   3. 每一步都打日志，失败不静默
 *   4. 不碰 NetworkSecurityConfig / Cronet / WebView（系统类，副作用大）
 */
'use strict';

Java.perform(function () {
    var TAG = '[unpin]';
    var ArrayList = Java.use('java.util.ArrayList');

    function step(name, fn) {
        try { fn(); console.log(TAG + ' [ok]   ' + name); }
        catch (e) { console.log(TAG + ' [skip] ' + name + '  -> ' + e); }
    }

    /* 1. Conscrypt：4 参数版 checkTrustedRecursive（Android 10+ 实际调用点） */
    step('TrustManagerImpl.checkTrustedRecursive', function () {
        var TMI = Java.use('com.android.org.conscrypt.TrustManagerImpl');
        TMI.checkTrustedRecursive.overload(
            '[Ljava.security.cert.X509Certificate;',
            '[B', '[B',
            'java.lang.String',
            'boolean',
            'java.util.ArrayList',
            'java.util.ArrayList',
            'java.util.Set'
        ).implementation = function () {
            return ArrayList.$new();
        };
    });

    /* 2. Conscrypt：verifyChain（上层入口，双保险） */
    step('TrustManagerImpl.verifyChain', function () {
        var TMI = Java.use('com.android.org.conscrypt.TrustManagerImpl');
        TMI.verifyChain.overload(
            'java.util.List', 'java.util.List', 'java.lang.String',
            'boolean', '[B', '[B'
        ).implementation = function () {
            return ArrayList.$new();
        };
    });

    /* 3. OkHttp3（抖音里通常没有这个类，找不到就跳过，但会打日志） */
    step('okhttp3.CertificatePinner.check', function () {
        var CP = Java.use('okhttp3.CertificatePinner');
        CP.check.overload('java.lang.String', 'java.util.List').implementation = function (h) {
            console.log(TAG + ' [okhttp] bypass pin: ' + h);
        };
    });

    console.log(TAG + ' ready');
});
