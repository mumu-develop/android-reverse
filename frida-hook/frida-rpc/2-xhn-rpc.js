let StrMd5 = null;
let DeviceSecretHelper = null;
// 懒加载 + Java.performNow 万能
function ensureInit() {
    if (StrMd5 && DeviceSecretHelper) return;
    Java.performNow(function () {
        StrMd5 = Java.use("com.tj.tjbase.utils.StrMd5");
        DeviceSecretHelper = Java.use("com.tj.tjbase.http.DeviceSecretHelper");
        console.log("[init] classes loaded");
    });
}

function getMd5(str) {
    try {
        ensureInit();
        let result = StrMd5.MD5(str);
        return result !== null ? result.toString() : null;
    } catch (e) {
        return "__ERROR__: " + e;
    }
}

function getReqsign() {
    try {
        ensureInit();
        let result = DeviceSecretHelper.getSign();
        return result !== null ? result.toString() : null;
    } catch (e) {
        return "__ERROR__: " + e;
    }
}

function getReqDeviceId() {
    try {
        ensureInit();
        let result = DeviceSecretHelper.getDeviceSecretId();
        return result !== null ? result.toString() : null;
    } catch (e) {
        return "__ERROR__: " + e;
    }
}

rpc.exports = {
    md5method: getMd5,
    reqsignmethod: getReqsign,
    reqdeviceidmethod: getReqDeviceId
};