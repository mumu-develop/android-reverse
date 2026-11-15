function showStacks() {
    var Exception = Java.use('java.lang.Exception');
    var stack = Exception.$new().getStackTrace();
    for (var i = 0; i < stack.length; i++) {
        console.log('\t' + stack[i].toString());
    }
}

function hook1(){
    let StrMd5 = Java.use("com.tj.tjbase.utils.StrMd5");
    StrMd5["MD5"].implementation = function (str) {
    console.log(`StrMd5.MD5 is called: str=${str}`);
    let result = this["MD5"](str);
    console.log(`StrMd5.MD5 result=${result}`);
    return result;
};
}


// 入口
function main() {
    // 调用入口
    Java.perform(function () {
        hook1()
    })
}

setImmediate(main)