// b43_gcd_lcm
const std = @import("std");
fn gcd(a0: i64, b0: i64) i64 {
    var a = a0; var b = b0;
    while (b != 0) { const t = b; b = @rem(a, b); a = t; }
    return a;
}
pub fn main() !void {
    const t0 = std.time.nanoTimestamp();
    var acc: i64 = 0;
    var i: i64 = 1;
    while (i <= 1000000) : (i += 1) acc += gcd(i, 1000000 - i + 1);
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ acc, t1 - t0 });
}
