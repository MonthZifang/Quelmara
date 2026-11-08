// b1_int —— 整数运算热循环，20M 次
const std = @import("std");
pub fn main() !void {
    const n: i64 = 20000000;
    const t0 = std.time.nanoTimestamp();
    var acc: i64 = 0;
    var i: i64 = 0;
    while (i < n) : (i += 1) acc += @rem(i * 7, 13);
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ acc, t1 - t0 });
}
