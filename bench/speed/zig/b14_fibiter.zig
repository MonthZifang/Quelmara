// b14_fibiter —— 迭代 fib(5000 万)
const std = @import("std");
pub fn main() !void {
    const n: i64 = 50000000;
    const t0 = std.time.nanoTimestamp();
    var a: i64 = 0; var b: i64 = 1;
    var i: i64 = 0;
    while (i < n) : (i += 1) {
        const t = a + b;
        a = b;
        b = @rem(t, 1000000007);
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ a, t1 - t0 });
}
