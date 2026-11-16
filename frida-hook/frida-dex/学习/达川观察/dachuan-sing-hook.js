// function showStacks() {
//     Java.perform(function () {
//         console.log(Java.use("android.util.Log").getStackTraceString(Java.use("java.lang.Exception").$new()));
//     });
// }
//
// Java.perform(function(){
//
//          var hash = Java.use("java.util.HashMap") // 没有走这个结构
//         hash.put.implementation = function (aa,bb){
//         console.log("key->",aa)
//         // console.log("val->",bb)
//         // if ()
//         // 跟栈调试
//
//         if(aa.toString() === "sign"){
//             console.log("查看堆栈")
//             showStacks()
//         }
//         var res = this.put(aa,bb)
//         return res
//     }
//
//     })


function hook_sign(){
    Java.perform(function(){
        let HttpRequestEntity = Java.use("cn.thecover.lib.http.data.entity.HttpRequestEntity");
        HttpRequestEntity["getSign"].implementation = function (str, str2, str3) {
        console.log(`HttpRequestEntity.getSign is called: str=${str}, str2=${str2}, str3=${str3}`);
        let result = this["getSign"](str, str2, str3);
        console.log(`HttpRequestEntity.getSign result=${result}`);
        return result;
};
    })

}


function getAppSign(){
    Java.perform(function(){
        let LogShutDown = Java.use("cn.thecover.lib.common.utils.LogShutDown");
        LogShutDown["getAppSign"].implementation = function () {
        console.log(`LogShutDown.getAppSign is called`);
        let result = this["getAppSign"]();
        console.log(`LogShutDown.getAppSign result=${result}`);
    return result;
};
    })
}

// hook_sign()
getAppSign()