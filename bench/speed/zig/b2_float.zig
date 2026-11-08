// b2_float —— 浮点运算：调和级数前 5M 项
const std = @import("std");
pub fn main() !void {
    const n: i64 = 5000000;
    const t0 = std.time.nanoTimestamp();
    var acc: f64 = 0.0;
    var i: i64 = 1;
    while (i <= n) : (i += 1) acc += 1.0 / @as(f64, @floatFromInt(i));
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d:.6}\nT\n{d}\n", .{ acc, t1 - t0 });
}
