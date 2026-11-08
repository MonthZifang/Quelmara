// b15_loopsum —— 最朴素循环累加 2 亿次
const std = @import("std");
pub fn main() !void {
    const n: i64 = 200000000;
    const t0 = std.time.nanoTimestamp();
    var s: i64 = 0;
    var x: i64 = 1;
    var i: i64 = 0;
    while (i < n) : (i += 1) {
        x = (x * 31 + i) | 1;
        s = s + (x & 1023);
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ s, t1 - t0 });
}
