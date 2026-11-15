function Hookdemo(){
    var utils = Java.use("com.luoge.com.Utils");
    utils.getCalc.implementation = function (a,b){
        console.log("a1 ||-" + a);
        console.log("a2 ||-" + b);
        var res = this.getCalc(a,b)
        console.log(res)
        return 888  // 篡改返回值
    }
}

function hook1(){
    var utils = Java.use("com.luoge.com.Utils")
     console.log(utils.getOver.overloads.length);
    utils.getOver.overload().implementation = function (){
        var res = this.getOver()
        console.log(res)
        return res
    }

    utils.getOver.overload("int").implementation = function (a){
        console.log("参数-》",a)
        var res = this.getOver(a)
        console.log(res)
        return res
    }

    // hook多重载
    let lens = utils.getOver.overloads.length
    for (var i=0; i < lens; i++){
        utils.getOver.overloads[i].implementation = function (){
            for (var a = 0; a<arguments.length;a++){
                console.log(a + '---' + arguments[a])
            }
            var res = this.getOver.apply(this,arguments);
            console.log(res)
            // 调用原始方法
            return res
        }
    }


}

function hook2(){
    var money = Java.use("com.luoge.com.Money");
    money.$init.overload('java.lang.String', 'int').implementation = function(str, num){
        console.log(str, num);
        str = "欧元";
        num = 2000;
        this.$init(str, num);
    }
}

// 测试算法 主动调用  动态传输
function hook3(){
     var Utils = Java.use("com.luoge.com.Utils");
      // 应用 hook 函数到静态方法
    var res =  Utils.test()
    console.log(res)

     var MD5 = Java.use("com.luoge.com.MD5");
    var res1 =  MD5.md5_1("1")
    console.log(res1)
}

function hook4(){
        //非静态字段的修改
        Java.choose("com.luoge.com.Money", {
            // 每找一次调用一次
            onMatch: function(obj){
                obj.num.value = 150000;
                obj._name.value = "xialuo"; // 字段名和方法名一致 加 _
                console.log(obj.getInfo())
            },
            onComplete: function(){
                console.log('内存中Money操作完毕')
            }
        });
}

function hook5(){
    var InnerClass = Java.use('com.luoge.com.Money$innerClass');
// 优化构造函数的 hook
InnerClass.$init.overload('java.lang.String', 'int').implementation = function(name, num) {
    console.log('Hooked innerClass constructor');
    console.log('Parameter name:', name);
    console.log('Parameter num:', num);
    // 调用原始构造函数
    name = "ooo"
    this.$init(name, num);
    console.log(this.outPrint())
    return this.$init(name, num);
};
}

function hook6(){
    // console.log(Java.enumerateLoadedClassesSync().join('\n'))
    var money = Java.use("com.luoge.com.Money");
    var methods = money.class.getDeclaredMethods()
    // console.log(methods)
    // for (var i=0;i<methods.length; i++){
    //     console.log(methods[i].getName())
    // }
    var Constructors = money.class.getDeclaredConstructors()
        // console.log(Constructors.join('\n'))

    var Fields = money.class.getDeclaredFields()
         // console.log(Fields.join('\n'))

        var Classes = money.class.getDeclaredClasses();
        console.log(Classes.join('\n'))
}

function main(){
    Java.perform(function (){
        hook5()
    })
}

main()

// 中场休息  加密动作  md5 getsign
