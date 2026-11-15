function showStacks() {
    Java.perform(function () {
        console.log(Java.use("android.util.Log").getStackTraceString(Java.use("java.lang.Exception").$new()));
    });
}

function hook1(){
    var YouthNetworkInterceptor = Java.use("cn.youth.news.network.api.YouthNetworkInterceptor");
YouthNetworkInterceptor["intercept"].implementation = function (chain) {
    console.log(`YouthNetworkInterceptor.intercept is called: chain=${chain}`);
    let result = this["intercept"](chain);
    console.log(`YouthNetworkInterceptor.intercept result=${result}`);
    return result;
};
}

function hook2(){
var YouthNetworkInterceptor = Java.use("cn.youth.news.network.api.YouthNetworkInterceptor");
YouthNetworkInterceptor["youthIntercept"].implementation = function (chain) {
    console.log(`YouthNetworkInterceptor.youthIntercept is called: chain=${chain}`);
    let result = this["youthIntercept"](chain);
    console.log(`YouthNetworkInterceptor.youthIntercept result=${result}`);
    return result;
};
}

function hook3(){
    var Request = Java.use("okhttp3.Request");
Request["url"].implementation = function () {
    console.log(`Request.url is called`);
    let result = this["url"]();
    console.log(`Request.url result=${result}`);
    return result;
};
}


function hook4(){
    var YouthNetworkInterceptor = Java.use("cn.youth.news.network.api.YouthNetworkInterceptor");
YouthNetworkInterceptor["getExtraParams"].implementation = function (version) {
    console.log(`YouthNetworkInterceptor.getExtraParams is called: version=${version}`);
    let result = this["getExtraParams"](version);
     var _mmm =  Java.cast(result,Java.use("java.util.TreeMap"))
    console.log(`YouthNetworkInterceptor.getExtraParams result=${_mmm}`);
    return result;
};
}


function hook5(){
    let YouthNetworkInterceptor = Java.use("cn.youth.news.network.api.YouthNetworkInterceptor");
    YouthNetworkInterceptor["signature"].implementation = function (map, i) {
    var _mmm =  Java.cast(map,Java.use("java.util.HashMap"))
    console.log(`YouthNetworkInterceptor.signature is called: map=${_mmm}, i=${i}`);
    let result = this["signature"](_mmm, i);
    console.log(`YouthNetworkInterceptor.signature result=${result}`);
    return result;
};
}


function hook6(){
    let YouthNetworkInterceptor = Java.use("cn.youth.news.network.api.YouthNetworkInterceptor");
    YouthNetworkInterceptor["encrypt"].implementation = function (map) {
    var _mmm =  Java.cast(map,Java.use("java.util.HashMap"))
    console.log(`YouthNetworkInterceptor.encrypt is called: map=${_mmm}`);
    let result = this["encrypt"](_mmm);
    console.log(`YouthNetworkInterceptor.encrypt result=${result}`);
    return result;
};
}


function hook7(){
    let ZQNetUtils = Java.use("cn.youth.news.network.ZQNetUtils");
    ZQNetUtils["getUrlParamEncode"].implementation = function (str) {
    console.log(`ZQNetUtils.getUrlParamEncode is called: str=${str}`);
    let result = this["getUrlParamEncode"](str);
    console.log(`ZQNetUtils.getUrlParamEncode result=${result}`);
    return result;
};
}


function hook8(){
    let PubKeySignature = Java.use("cn.youth.news.utils.PubKeySignature");
PubKeySignature["getSingInfo"].implementation = function (context, c2) {
    console.log(`PubKeySignature.getSingInfo is called: context=${context}, c2=${c2}`);
    let result = this["getSingInfo"](context, c2);
    console.log(`PubKeySignature.getSingInfo  sPublicKey=${result}`);
    return result;
};
}

function hook9(){
    var Builder = Java.use("okhttp3.FormBody$Builder");
    Builder.add.overload('java.lang.String', 'java.lang.String').implementation = function (k, v) {
        console.log("[FormBody.add] " + k + " = " + v);
        var stack = Java.use("android.util.Log").getStackTraceString(
            Java.use("java.lang.Throwable").$new()
        );
        console.log(stack);
        return this.add(k, v);
    };
}

function hook10(){
    let ArticlePreDataHelper = Java.use("cn.youth.news.ui.homearticle.articledetail.local.helper.ArticlePreDataHelper");
    ArticlePreDataHelper["httpGetDetailData"].implementation = function (article, callBackListener) {
    console.log(`ArticlePreDataHelper.httpGetDetailData is called: article=${article}, callBackListener=${callBackListener}`);
    let result = this["httpGetDetailData"](article, callBackListener);
    console.log(`ArticlePreDataHelper.httpGetDetailData result=${result}`);
    return result;
};
}
// 入口
function main() {
    // 调用入口
    Java.perform(function () {
       // hook10()
        // hook3()
        hook4()
        hook5()
        hook6()
        // hook9()
    })
}




setImmediate(main)