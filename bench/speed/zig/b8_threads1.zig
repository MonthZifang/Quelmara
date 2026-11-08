// b8_threads1 —— 单线程整数运算
const std = @import("std");
fn work(n: i64) i64 {
    var acc: i64 = 0;
    var i: i64 = 0;
    while (i < n) : (i += 1) acc += @rem(i * 7, 13);
    return acc;
}
pub fn main() !void {
    const t0 = std.time.nanoTimestamp();
    const r = work(160000000);
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ r, t1 - t0 });
}
