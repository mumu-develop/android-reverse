Java.perform(function () {

let g = Java.use("com.dianping.nvnetwork.g");
g["g"].implementation = function () {
    console.log(`----- hook success --- return 3`);
    return 3;
};

});

