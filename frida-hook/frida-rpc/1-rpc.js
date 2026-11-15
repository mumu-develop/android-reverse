function fridamethod01(inputStr){
    var result = null;
    Java.perform(function(){
        var targetClass = Java.use("com.luoge.com.MD5");
        result = targetClass.md5_1(inputStr);
    });
    return result;
}


// rpc.exports = {
//     invokemethod01: fridamethod01,
// }



function xhnRmtHash (arg){
    let result = null;
    Java.perform(function(){
        let MD5Tools = Java.use("cn.com.voc.composebase.utils.MD5Tools");
        result = MD5Tools["b"](arg);
    })
    return result;
}

rpc.exports = {
    xhnmethod: xhnRmtHash,
}



// Java.perform(function(){
//         let MD5Tools = Java.use("cn.com.voc.composebase.utils.MD5Tools");
//         MD5Tools["b"].implementation = function (str) {
//         console.log(`MD5Tools.b is called: str=${str}`);
//         let result = this["b"](str);
//         console.log(`MD5Tools.b result=${result}`);
//         return result;
// };
//     })