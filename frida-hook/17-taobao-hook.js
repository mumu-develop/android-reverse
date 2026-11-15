
Java.perform(function (){
    let SwitchConfig = Java.use("mtopsdk.mtop.global.SwitchConfig");
SwitchConfig["isGlobalSpdySwitchOpen"].implementation = function () {
    console.log(`SwitchConfig.isGlobalSpdySwitchOpen is called`);
    let result = this["isGlobalSpdySwitchOpen"]();
    console.log(`SwitchConfig.isGlobalSpdySwitchOpen result=${result}`);
    return false;
};
})