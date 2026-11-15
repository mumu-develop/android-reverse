function fmtSockaddr(sa) {
    try {
        if (sa.isNull()) return '(connected)';   // NULL = 已连接的 TCP socket
        var family = sa.readU16();
        if (family === 2) {                      // AF_INET
            var port = (sa.add(2).readU8() << 8) | sa.add(3).readU8();
            var ip = [4,5,6,7].map(function (i) { return sa.add(i).readU8(); }).join('.');
            return ip + ':' + port;
        }
        if (family === 10) return 'ipv6';
        return 'family=' + family;
    } catch (e) { return 'err'; }
}

function hex(buf, len, max) {
    try {
        var n = Math.min(len, max);
        var a = new Uint8Array(buf.readByteArray(n));
        var s = '';
        for (var i = 0; i < a.length; i++) {
            s += ('0' + a[i].toString(16)).slice(-2) + ' ';
            if ((i + 1) % 16 === 0) s += '\n';
        }
        return s;
    } catch (e) { return '<err>'; }
}

// 1) 先看谁连了谁
var connectAddr = Module.findExportByName(null, 'connect');
if (connectAddr) {
    Interceptor.attach(connectAddr, {
        onEnter: function (args) {
            console.log('[connect] fd=' + args[0].toInt32() + ' -> ' + fmtSockaddr(args[1]));
        }
    });
}

// 2) 收发都看
['sendto', 'recvfrom'].forEach(function (fn) {
    var addr = Module.findExportByName(null, fn);
    if (!addr) { console.log('[-] ' + fn + ' not found'); return; }
    Interceptor.attach(addr, {
        onEnter: function (args) {
            this.fd  = args[0].toInt32();
            this.buf = args[1];
            this.len = args[2].toInt32();
            this.sa  = args[4];
        },
        onLeave: function (retval) {
            var n = retval.toInt32();
            if (n <= 0) return;
            var tgt = this.sa.isNull() ? '(connected)' : fmtSockaddr(this.sa);
            if (tgt.indexOf(':53') > -1) return;   // 过滤 DNS
            console.log('[' + fn + '] fd=' + this.fd + ' tgt=' + tgt + ' len=' + n);
            if (n <= 512) console.log(hex(this.buf, n, 128));
        }
    });
});




setTimeout(fmtSockaddr,1000)