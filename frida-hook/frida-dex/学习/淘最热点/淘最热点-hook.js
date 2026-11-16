function showStacks() {
    Java.perform(function () {
        console.log(Java.use("android.util.Log").getStackTraceString(Java.use("java.lang.Exception").$new()));
    });
}
function hook1(){
    var hash = Java.use("java.util.HashMap") // 没有走这个结构
    hash.put.implementation = function (aa,bb){
        console.log("key->",aa)
        console.log("val->",bb)
        // if ()
        // 跟栈调试
        if(aa.toString() === "sign"){
            console.log("查看堆栈")
            showStacks()
        }
        var res = this.put(aa,bb)
        return res
    }
}


function sign(){
    Java.perform(function(){
        var TreUtil = Java.use("com.maihan.tredian.util.TreUtil");
        TreUtil["sign"].implementation = function (str) {
        console.log(`TreUtil.sign is called: str=${str}`);
        let result = this["sign"](str);
        console.log(`TreUtil.sign result=${result}`);
        return result;
};
    })
}

setTimeout(sign,500)