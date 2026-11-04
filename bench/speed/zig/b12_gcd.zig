// b12_gcd —— 整数：3000 万次辗转相除
const std = @import("std");
fn gcd(a: i64, b: i64) i64 {
    var x = a; var y = b;
    while (y != 0) { const t = y; y = @rem(x, y); x = t; }
    return x;
}
pub fn main() !void {
    const n: i64 = 30000000;
    const t0 = std.time.nanoTimestamp();
    var s: i64 = 0;
    var i: i64 = 1;
    while (i <= n) : (i += 1) s += gcd(i, 1000000 - i);
    const t1 = std.time.nanoTimestamp();
    std.debug.print("{d}\nT\n{d}\n", .{ s, t1 - t0 });
}
