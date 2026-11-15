// ============================================================
// 算法自吐 v3 —— 覆盖 JCE/安全 API 的重载
// 输出：算法 → 调用栈 → key/iv → 输入 → 输出
//
// 覆盖：
//   MessageDigest  getInstance ×3 / update(byte,[B,[B ii) / digest([B ii,无参)
//   Mac            getInstance ×3 / init(Key,Spec) / update(byte,[B,[B ii) / doFinal([B i,无参)
//   Cipher         getInstance ×3 / init(Key,Srand,Spec,Spec+Srand) /
//                  update([B,[B ii) / doFinal([B i,[B ii,无参)
//   Signature      getInstance ×3 / initSign ×2 / initVerify ×3 /
//                  update(byte,[B,[B ii) / sign() / verify([B,[B ii)
//   Base64         decode ×3 / encode ×2 / encodeToString ×2
//   密钥规格        DESKeySpec / SecretKeySpec / IvParameterSpec / X509EncodedKeySpec
//
// 不覆盖（工具边界，非 bug）：
//   - so 里 native 实现的算法（只能 unidbg / IDA）
//   - BouncyCastle 轻量 API（SM4Engine / SM3Digest 等，不走 JCE）
//   - 自实现的 MD5/AES、WebView 里的 JS 加密
//   - ByteBuffer 版重载（位置会变，读出来会破坏原文）
// ============================================================

var _loging = true          // 总开关
var _showUpdate = false     // 打印每次 update
var _stack = true           // 打印调用栈
var _stackDepth = 15        // 栈最多几层

var _seq = 0
var _t0 = Date.now()

function _log() {
    if (_loging) console.log.apply(console, arguments)
}

// ---------------- 转换 ----------------
function bytesToHex(arr) {
    var str = ""
    for (var i = 0; i < arr.length; i++) {
        var tmp = arr[i]
        if (tmp < 0) tmp = (255 + tmp + 1).toString(16)
        else tmp = tmp.toString(16)
        if (tmp.length == 1) tmp = "0" + tmp
        str += tmp
    }
    return str
}

function bytesToBase64(e) {
    var chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
    var r, a, c, h, o, t
    for (c = e.length, a = 0, r = ''; a < c;) {
        if (h = 255 & e[a++], a == c) {
            r += chars.charAt(h >> 2)
            r += chars.charAt((3 & h) << 4)
            r += '=='
            break
        }
        if (o = e[a++], a == c) {
            r += chars.charAt(h >> 2)
            r += chars.charAt((3 & h) << 4 | (240 & o) >> 4)
            r += chars.charAt((15 & o) << 2)
            r += '='
            break
        }
        t = e[a++]
        r += chars.charAt(h >> 2)
        r += chars.charAt((3 & h) << 4 | (240 & o) >> 4)
        r += chars.charAt((15 & o) << 2 | (192 & t) >> 6)
        r += chars.charAt(63 & t)
    }
    return r
}

function tryUtf8(arr) {
    if (!arr || arr.length === 0) return ""
    var s = ""
    for (var i = 0; i < arr.length; i++) {
        var c = arr[i] & 0xff
        if (c === 0) break
        if (c < 0x20 || c > 0x7e) return null
        s += String.fromCharCode(c)
    }
    return s.length >= 2 ? s : null
}

function bufToArray(buf) {
    var out = []
    if (!buf) return out
    for (var i = 0; i < buf.length; i++) out.push(buf[i])
    return out
}

function sliceBytes(arr, off, len) {
    var out = []
    for (var i = 0; i < len; i++) out.push(arr[off + i])
    return out
}

// ---------------- 栈 ----------------
var _Thread = null

function javaStack() {
    if (!_stack) return ""
    try {
        if (!_Thread) _Thread = Java.use("java.lang.Thread")
        var st = _Thread.currentThread().getStackTrace()
        var out = []
        for (var i = 0; i < st.length && out.length < _stackDepth; i++) {
            var ln = st[i].toString()
            if (ln.indexOf("frida") >= 0 || ln.indexOf("dalvik.system") >= 0 ||
                ln.indexOf("com.android.internal.os") >= 0 || ln.indexOf("java.lang.Thread") >= 0) {
                continue
            }
            out.push("      at " + ln)
        }
        return out.join("\n")
    } catch (e) {
        return ""
    }
}

// ---------------- 输出 ----------------
function hhmmss() {
    return ((Date.now() - _t0) / 1000).toFixed(3) + "s"
}

function id() {
    return ++_seq
}

function header(label) {
    _log("[" + id() + "] " + label + "   @" + hhmmss())
    var s = javaStack()
    if (s) _log("    调用栈 :\n" + s)
}

function dumpIn(inputBytes) {
    if (!inputBytes || !inputBytes.length) return
    var s = tryUtf8(inputBytes)
    if (s !== null && s.length) _log('    输入 : "' + s + '"')
    _log("    输入 hex : " + bytesToHex(inputBytes))
}

function dumpOut(outBytes) {
    if (!outBytes || !outBytes.length) return
    _log("    输出 hex : " + bytesToHex(outBytes))
    _log("    输出 b64 : " + bytesToBase64(outBytes))
    var s = tryUtf8(outBytes)
    if (s !== null && s.length >= 4) _log('    输出 str : "' + s + '"')
}

function block(label, inputBytes, outBytes) {
    header(label)
    dumpIn(inputBytes)
    dumpOut(outBytes)
    _log("")
}

// ---------------- 状态 ----------------
var STATE = {}

function keyOf(obj) {
    try { return obj.hashCode() } catch (e) { return -1 }
}

function stateOf(obj, alg) {
    var k = keyOf(obj)
    if (!STATE[k]) STATE[k] = { alg: alg || "?", parts: [], key: null, iv: null }
    if (alg) STATE[k].alg = alg
    return STATE[k]
}

function dropState(obj) {
    try { delete STATE[keyOf(obj)] } catch (e) {}
}

function push(st, bytes) {
    var arr = bufToArray(bytes)
    st.parts = st.parts.concat(arr)
    if (_showUpdate) {
        var s = tryUtf8(arr)
        _log("    update in : " + (s !== null ? '"' + s + '"' : bytesToHex(arr)))
    }
}

// ---------------- hook 工具 ----------------
function tryHook(cls, name, types, impl) {
    try {
        var m = cls[name]
        if (!types || types.length === 0) m.overload().implementation = impl
        else if (types.length === 1) m.overload(types[0]).implementation = impl
        else if (types.length === 2) m.overload(types[0], types[1]).implementation = impl
        else if (types.length === 3) m.overload(types[0], types[1], types[2]).implementation = impl
        else if (types.length === 4) m.overload(types[0], types[1], types[2], types[3]).implementation = impl
        return true
    } catch (e) {
        return false
    }
}

function main() {
    Java.perform(function () {
        _log("算法助手已开启（v3，覆盖重载）")

        // ==================== MessageDigest ====================
        var MD = Java.use("java.security.MessageDigest")

        tryHook(MD, "getInstance", ["java.lang.String"], function (alg) {
            var r = this.getInstance(alg); stateOf(r, alg); return r
        })
        tryHook(MD, "getInstance", ["java.lang.String", "java.lang.String"], function (alg, p) {
            var r = this.getInstance(alg, p); stateOf(r, alg); return r
        })
        tryHook(MD, "getInstance", ["java.lang.String", "java.security.Provider"], function (alg, p) {
            var r = this.getInstance(alg, p); stateOf(r, alg); return r
        })

        tryHook(MD, "update", ["byte"], function (b) {
            push(stateOf(this), [b & 0xff]); return this.update(b)
        })
        tryHook(MD, "update", ["[B"], function (a) {
            push(stateOf(this), a); return this.update(a)
        })
        tryHook(MD, "update", ["[B", "int", "int"], function (a, o, l) {
            push(stateOf(this), sliceBytes(bufToArray(a), o, l)); return this.update(a, o, l)
        })

        tryHook(MD, "digest", [], function () {
            var st = stateOf(this); var r = this.digest()
            block(st.alg, st.parts, bufToArray(r)); dropState(this); return r
        })
        tryHook(MD, "digest", ["[B"], function (a) {
            var st = stateOf(this); var seg = sliceBytes(bufToArray(a), 0, a.length)
            var r = this.digest(a)
            block(st.alg, st.parts.concat(seg), bufToArray(r)); dropState(this); return r
        })
        tryHook(MD, "digest", ["[B", "int", "int"], function (a, o, l) {
            var st = stateOf(this); var seg = sliceBytes(bufToArray(a), o, l)
            var r = this.digest(a, o, l)
            block(st.alg, st.parts.concat(seg), bufToArray(r)); dropState(this); return r
        })

        // ==================== Mac (HMAC) ====================
        var Mac = Java.use("javax.crypto.Mac")

        tryHook(Mac, "getInstance", ["java.lang.String"], function (alg) {
            var r = this.getInstance(alg); stateOf(r, alg); return r
        })
        tryHook(Mac, "getInstance", ["java.lang.String", "java.lang.String"], function (alg, p) {
            var r = this.getInstance(alg, p); stateOf(r, alg); return r
        })
        tryHook(Mac, "getInstance", ["java.lang.String", "java.security.Provider"], function (alg, p) {
            var r = this.getInstance(alg, p); stateOf(r, alg); return r
        })

        tryHook(Mac, "init", ["java.security.Key"], function (k) {
            var st = stateOf(this)
            try { var e = k.getEncoded(); if (e) st.key = { alg: k.getAlgorithm(), bytes: bufToArray(e) } } catch (x) { }
            return this.init(k)
        })
        tryHook(Mac, "init", ["java.security.Key", "java.security.spec.AlgorithmParameterSpec"], function (k, s) {
            var st = stateOf(this)
            try { var e = k.getEncoded(); if (e) st.key = { alg: k.getAlgorithm(), bytes: bufToArray(e) } } catch (x) { }
            return this.init(k, s)
        })

        tryHook(Mac, "update", ["byte"], function (b) {
            push(stateOf(this), [b & 0xff]); return this.update(b)
        })
        tryHook(Mac, "update", ["[B"], function (a) {
            push(stateOf(this), a); return this.update(a)
        })
        tryHook(Mac, "update", ["[B", "int", "int"], function (a, o, l) {
            push(stateOf(this), sliceBytes(bufToArray(a), o, l)); return this.update(a, o, l)
        })

        tryHook(Mac, "doFinal", [], function () {
            var st = stateOf(this); var r = this.doFinal()
            header(st.alg)
            if (st.key) _log("    key  : " + st.key.alg + " / " + bytesToHex(st.key.bytes))
            dumpIn(st.parts); dumpOut(bufToArray(r)); _log("")
            dropState(this); return r
        })
        tryHook(Mac, "doFinal", ["[B"], function (a) {
            var st = stateOf(this); var seg = bufToArray(a)
            var r = this.doFinal(a)
            header(st.alg)
            if (st.key) _log("    key  : " + st.key.alg + " / " + bytesToHex(st.key.bytes))
            dumpIn(st.parts.concat(seg)); dumpOut(bufToArray(r)); _log("")
            dropState(this); return r
        })
        tryHook(Mac, "doFinal", ["[B", "int"], function (a, off) {
            var st = stateOf(this); var seg = sliceBytes(bufToArray(a), 0, off)
            var r = this.doFinal(a, off)
            header(st.alg)
            if (st.key) _log("    key  : " + st.key.alg + " / " + bytesToHex(st.key.bytes))
            dumpIn(st.parts.concat(seg)); dumpOut(bufToArray(r)); _log("")
            dropState(this); return r
        })

        // ==================== Cipher ====================
        var Cipher = Java.use("javax.crypto.Cipher")

        tryHook(Cipher, "getInstance", ["java.lang.String"], function (t) {
            var r = this.getInstance(t); stateOf(r, t); return r
        })
        tryHook(Cipher, "getInstance", ["java.lang.String", "java.lang.String"], function (t, p) {
            var r = this.getInstance(t, p); stateOf(r, t + " / " + p); return r
        })
        tryHook(Cipher, "getInstance", ["java.lang.String", "java.security.Provider"], function (t, p) {
            var r = this.getInstance(t, p); stateOf(r, t); return r
        })

        function cipherInit(mode, key, spec) {
            var st = stateOf(this)
            try {
                var e = key.getEncoded()
                if (e) st.key = { alg: key.getAlgorithm(), bytes: bufToArray(e) }
            } catch (x) { }
            try {
                var iv = spec.getIV()
                if (iv) st.iv = bufToArray(iv)
            } catch (x) { }
        }

        tryHook(Cipher, "init", ["int", "java.security.Key"], function (m, k) {
            cipherInit.call(this, m, k, null); return this.init(m, k)
        })
        tryHook(Cipher, "init", ["int", "java.security.Key", "java.security.SecureRandom"], function (m, k, r) {
            cipherInit.call(this, m, k, null); return this.init(m, k, r)
        })
        tryHook(Cipher, "init", ["int", "java.security.Key", "java.security.spec.AlgorithmParameterSpec"], function (m, k, s) {
            cipherInit.call(this, m, k, s); return this.init(m, k, s)
        })
        tryHook(Cipher, "init", ["int", "java.security.Key", "java.security.spec.AlgorithmParameterSpec", "java.security.SecureRandom"], function (m, k, s, r) {
            cipherInit.call(this, m, k, s); return this.init(m, k, s, r)
        })

        tryHook(Cipher, "update", ["[B"], function (a) {
            push(stateOf(this), a); return this.update(a)
        })
        tryHook(Cipher, "update", ["[B", "int", "int"], function (a, o, l) {
            push(stateOf(this), sliceBytes(bufToArray(a), o, l)); return this.update(a, o, l)
        })

        function cipherOut(st, inputBytes, outBytes) {
            header(st.alg)
            if (st.key) _log("    key  : " + st.key.alg + " / " + bytesToHex(st.key.bytes))
            if (st.iv && /CBC|CFB|OFB|CTR|CTS/i.test(st.alg)) _log("    iv   : " + bytesToHex(st.iv))
            dumpIn(inputBytes)
            dumpOut(outBytes)
            _log("")
        }

        tryHook(Cipher, "doFinal", [], function () {
            var st = stateOf(this); var r = this.doFinal()
            cipherOut(st, st.parts, bufToArray(r)); dropState(this); return r
        })
        tryHook(Cipher, "doFinal", ["[B"], function (a) {
            var st = stateOf(this); var seg = bufToArray(a)
            var r = this.doFinal(a)
            cipherOut(st, st.parts.concat(seg), bufToArray(r)); dropState(this); return r
        })
        tryHook(Cipher, "doFinal", ["[B", "int"], function (a, off) {
            var st = stateOf(this); var seg = sliceBytes(bufToArray(a), 0, off)
            var r = this.doFinal(a, off)
            cipherOut(st, st.parts.concat(seg), bufToArray(r)); dropState(this); return r
        })
        tryHook(Cipher, "doFinal", ["[B", "int", "int"], function (a, off, len) {
            var st = stateOf(this); var seg = sliceBytes(bufToArray(a), off, len)
            var r = this.doFinal(a, off, len)
            cipherOut(st, st.parts.concat(seg), bufToArray(r)); dropState(this); return r
        })

        // ==================== Signature (RSA/ECDSA 签名) ====================
        var Sig = Java.use("java.security.Signature")

        tryHook(Sig, "getInstance", ["java.lang.String"], function (alg) {
            var r = this.getInstance(alg); stateOf(r, alg); return r
        })
        tryHook(Sig, "getInstance", ["java.lang.String", "java.lang.String"], function (alg, p) {
            var r = this.getInstance(alg, p); stateOf(r, alg); return r
        })
        tryHook(Sig, "getInstance", ["java.lang.String", "java.security.Provider"], function (alg, p) {
            var r = this.getInstance(alg, p); stateOf(r, alg); return r
        })

        function sigInit(kind) {
            return function (key, rnd) {
                var st = stateOf(this)
                try { st.key = { alg: key.getAlgorithm(), bytes: bufToArray(key.getEncoded()) } } catch (x) { }
                st.kind = kind
                if (rnd === undefined) return this["init" + kind](key)
                return this["init" + kind](key, rnd)
            }
        }
        tryHook(Sig, "initSign", ["java.security.PrivateKey"], sigInit("Sign"))
        tryHook(Sig, "initSign", ["java.security.PrivateKey", "java.security.SecureRandom"], sigInit("Sign"))
        tryHook(Sig, "initVerify", ["java.security.PublicKey"], sigInit("Verify"))
        tryHook(Sig, "initVerify", ["java.security.PublicKey", "java.security.SecureRandom"], sigInit("Verify"))
        tryHook(Sig, "initVerify", ["java.security.cert.Certificate"], function (cert) {
            var st = stateOf(this)
            try { st.key = { alg: "certificate", bytes: bufToArray(cert.getPublicKey().getEncoded()) } } catch (x) { }
            return this.initVerify(cert)
        })

        tryHook(Sig, "update", ["byte"], function (b) {
            push(stateOf(this), [b & 0xff]); return this.update(b)
        })
        tryHook(Sig, "update", ["[B"], function (a) {
            push(stateOf(this), a); return this.update(a)
        })
        tryHook(Sig, "update", ["[B", "int", "int"], function (a, o, l) {
            push(stateOf(this), sliceBytes(bufToArray(a), o, l)); return this.update(a, o, l)
        })

        tryHook(Sig, "sign", [], function () {
            var st = stateOf(this); var r = this.sign()
            block(st.alg + " (sign)", st.parts, bufToArray(r)); dropState(this); return r
        })
        tryHook(Sig, "verify", ["[B"], function (a) {
            var st = stateOf(this); var ok = this.verify(a)
            header(st.alg + " (verify)")
            dumpIn(st.parts)
            _log("    待验签 : " + bytesToHex(bufToArray(a)))
            _log("    结果 : " + ok)
            _log("")
            dropState(this); return ok
        })
        tryHook(Sig, "verify", ["[B", "int", "int"], function (a, o, l) {
            var st = stateOf(this); var ok = this.verify(a, o, l)
            header(st.alg + " (verify)")
            dumpIn(st.parts)
            _log("    待验签 : " + bytesToHex(sliceBytes(bufToArray(a), o, l)))
            _log("    结果 : " + ok)
            _log("")
            dropState(this); return ok
        })

        // ==================== Base64 ====================
        var B64 = Java.use("android.util.Base64")

        tryHook(B64, "decode", ["java.lang.String", "int"], function (s, f) {
            var r = this.decode(s, f)
            header("Base64.decode")
            _log("    输入 : " + s)
            _log("    输出 hex : " + bytesToHex(bufToArray(r)))
            _log("")
            return r
        })
        tryHook(B64, "decode", ["[B", "int"], function (a, f) {
            var r = this.decode(a, f)
            header("Base64.decode")
            dumpIn(bufToArray(a))
            _log("    输出 hex : " + bytesToHex(bufToArray(r)))
            _log("")
            return r
        })
        tryHook(B64, "decode", ["[B", "int", "int", "int"], function (a, o, l, f) {
            var r = this.decode(a, o, l, f)
            header("Base64.decode")
            dumpIn(sliceBytes(bufToArray(a), o, l))
            _log("    输出 hex : " + bytesToHex(bufToArray(r)))
            _log("")
            return r
        })

        tryHook(B64, "encodeToString", ["[B", "int"], function (a, f) {
            var r = this.encodeToString(a, f)
            header("Base64.encodeToString")
            dumpIn(bufToArray(a))
            _log("    输出 : " + r)
            _log("")
            return r
        })
        tryHook(B64, "encodeToString", ["[B", "int", "int", "int"], function (a, o, l, f) {
            var r = this.encodeToString(a, o, l, f)
            header("Base64.encodeToString")
            dumpIn(sliceBytes(bufToArray(a), o, l))
            _log("    输出 : " + r)
            _log("")
            return r
        })
        tryHook(B64, "encode", ["[B", "int"], function (a, f) {
            var r = this.encode(a, f)
            header("Base64.encode")
            dumpIn(bufToArray(a))
            _log("    输出 b64 : " + bytesToBase64(bufToArray(r)))
            _log("")
            return r
        })
        tryHook(B64, "encode", ["[B", "int", "int", "int"], function (a, o, l, f) {
            var r = this.encode(a, o, l, f)
            header("Base64.encode")
            dumpIn(sliceBytes(bufToArray(a), o, l))
            _log("    输出 b64 : " + bytesToBase64(bufToArray(r)))
            _log("")
            return r
        })

        // ==================== 密钥 / IV ====================
        tryHook(Java.use("javax.crypto.spec.DESKeySpec"), "$init", ["[B"], function (b) {
            _log("[KEY] DESKeySpec : " + bytesToHex(bufToArray(b))); return this.$init(b)
        })
        tryHook(Java.use("javax.crypto.spec.SecretKeySpec"), "$init", ["[B", "java.lang.String"], function (b, alg) {
            _log("[KEY] SecretKeySpec(" + alg + ") : " + bytesToHex(bufToArray(b)))
            return this.$init(b, alg)
        })
        tryHook(Java.use("javax.crypto.spec.IvParameterSpec"), "$init", ["[B"], function (b) {
            _log("[IV ] IvParameterSpec : " + bytesToHex(bufToArray(b))); return this.$init(b)
        })
        tryHook(Java.use("javax.crypto.spec.IvParameterSpec"), "$init", ["[B", "int", "int"], function (a, o, l) {
            _log("[IV ] IvParameterSpec : " + bytesToHex(sliceBytes(bufToArray(a), o, l)))
            return this.$init(a, o, l)
        })
        tryHook(Java.use("java.security.spec.X509EncodedKeySpec"), "$init", ["[B"], function (a) {
            _log("[KEY] X509EncodedKeySpec(b64) : " + bytesToBase64(bufToArray(a)))
            return this.$init(a)
        })

        var KF = Java.use("java.security.KeyFactory")
        tryHook(KF, "getInstance", ["java.lang.String"], function (alg) {
            _log("[ALG] KeyFactory : " + alg); return this.getInstance(alg)
        })
        var SKF = Java.use("javax.crypto.SecretKeyFactory")
        tryHook(SKF, "getInstance", ["java.lang.String"], function (alg) {
            _log("[ALG] SecretKeyFactory : " + alg); return this.getInstance(alg)
        })
    })
}

setImmediate(main)