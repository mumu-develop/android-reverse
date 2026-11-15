const crypto = require('crypto');

function md5Upper(str) {
    return crypto.createHash('md5').update(str, 'utf8').digest('hex').toUpperCase();
}

function sortMapByKey(map) {
    const sorted = {};
    Object.keys(map).sort().forEach(k => { sorted[k] = map[k]; });
    return sorted;
}

function paraMap(addMap, append) {
    try {
        const list = [];
        for (const keyName of Object.keys(addMap)) {
            list.push(keyName + "=" + addMap[keyName]);
        }
        list.sort();

        let builder = "";
        for (let i = 0; i < list.length; i++) {
            builder += list[i] + "&";
        }
        builder += "key=" + append;

        const checkCode = md5Upper(builder);
        addMap["sign"] = checkCode;

        const result = JSON.stringify(sortMapByKey(addMap));
        return result;
    } catch (e) {
        console.log(e);
        return "";
    }
}

// 你给的原始数据
const addMap = {
    "loginImei": "Android869169025308399",
    "equtype": "ANDROID",
    "userPwd": "123",
    "username": "123"
};

// 补上 timeStamp —— 对应 Java 的 System.currentTimeMillis() + ""
const time = Date.now() + "";
addMap["timeStamp"] = time;

base_append  = 'sdlkjsdljf0j2fsjk'
const code = paraMap(addMap, base_append);
console.log(code);


/**
 * 对应 Java 的 DesSecurity.encrypt64 + Map 处理
 * @param {string} code   明文（要加密的内容）
 * @param {string} desKey 密钥（对应 Java 的 key）
 * @param {string} desIV  偏移量（对应 Java 的 iv，必须 8 字节）
 * @returns {string} 加密后的 Base64 字符串
 */
function encodeDesMap(code, desKey, desIV) {
    // 1. 对应 MessageDigest md5(secKey.getBytes())
    const md5 = crypto.createHash('md5').update(Buffer.from(desKey, 'utf8')).digest();

    // 2. 对应 DESKeySpec(md.digest()) —— 只取前 8 字节
    const key8 = md5.slice(0, 8);

    // 3. IV 必须是 8 字节
    const iv8 = Buffer.from(desIV, 'utf8').slice(0, 8);

    // 4. 对应 Cipher "DES/CBC/PKCS5Padding" 加密
    const cipher = crypto.createCipheriv('des-cbc', key8, iv8);
    const encrypted = Buffer.concat([
        cipher.update(Buffer.from(code, 'utf8')),
        cipher.final()
    ]);

    // 5. 对应 Base64.encodeToString(..., 0) —— 无换行
    return encrypted.toString('base64');
}

desKey = '65102933'
desIV = '32028092'
const encrypt= encodeDesMap(code, desKey, desIV)
console.log(encrypt);