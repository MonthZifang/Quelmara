// b74_accum_poly
const std = @import("std");
pub fn main() !void {
    const t0 = std.time.nanoTimestamp();
    var acc: i64 = 0;
    var n: i64 = 1;
    while (n <= 5000000) : (n += 1) {
        var s: i64 = 0;
        var k: i64 = 0;
        while (k < 5) : (k += 1) s = s * n + k * 3 + 1;
        acc += @rem(s, 1000003);
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ @rem(acc, 1000003), t1 - t0 });
}
