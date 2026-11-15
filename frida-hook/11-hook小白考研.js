function showStacks() {
    var Exception = Java.use('java.lang.Exception');
    var stack = Exception.$new().getStackTrace();
    for (var i = 0; i < stack.length; i++) {
        console.log('\t' + stack[i].toString());
    }
}

function hook1(){
    var hash = Java.use("java.util.HashMap") // 没有走这个结构
    hash.put.implementation = function (aa,bb){
        console.log("key->",aa)
        console.log("val->",bb)
        // if ()
        // 跟栈调试

        if(aa.toString() === "data"){
            console.log("查看堆栈")
            showStacks()
        }
        var res = this.put(aa,bb)
        return res
    }
}


function hook2(){
    let Companion = Java.use("com.xbkaoyan.libcore.rsa.RSA$Companion");
    Companion["rsaEncode"].implementation = function (str) {
    console.log(`Companion.rsaEncode is called: str=${str}`);
    let result = this["rsaEncode"](str);
    console.log(`Companion.rsaEncode result=${result}`);
    return result;
};
}

// 入口
Java.perform(function () {
    hook2();
});