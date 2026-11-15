function hookAddRequestMap(){
    let JsonRequest = Java.use("com.dodonew.online.http.JsonRequest");
    JsonRequest["addRequestMap"].overload('java.util.Map', 'int').implementation = function (addMap, a) {
    console.log(`JsonRequest.addRequestMap is called: addMap=${JSON.stringify(javaMapToJs(addMap), null, 2)}, a=${a}`);
    this["addRequestMap"](addMap, a);
};
}

function javaMapToJs(mapObj) {
    var JMap = Java.use('java.util.Map');
    var map = Java.cast(mapObj, JMap);
    var result = {};
    var it = map.keySet().iterator();
    while (it.hasNext()) {
        var k = it.next();
        result[k.toString()] = map.get(k).toString();
    }
    return result;
}



function paraMap(){
    let RequestUtil = Java.use("com.dodonew.online.http.RequestUtil");
    RequestUtil["paraMap"].overload('java.util.Map', 'java.lang.String', 'java.lang.String').implementation = function (addMap, append, sign) {
    console.log(`RequestUtil.paraMap is called: addMap=${JSON.stringify(javaMapToJs(addMap), null, 2)}, append=${append}, sign=${sign}`);
    let result = this["paraMap"](addMap, append, sign);
    console.log(`RequestUtil.paraMap result=${result}`);
    return result;
};
}


// 入口
function main(){
    Java.perform(function (){
        paraMap()
    })
}

main()