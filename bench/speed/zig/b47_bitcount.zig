// b47_bitcount
const std = @import("std");
fn popcount(x0: i64) i64 {
    var x = x0; var c: i64 = 0;
    while (x != 0) { c += x & 1; x >>= 1; }
    return c;
}
pub fn main() !void {
    const t0 = std.time.nanoTimestamp();
    var acc: i64 = 0;
    var i: i64 = 0;
    while (i < 10000000) : (i += 1) acc += popcount(i);
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ acc, t1 - t0 });
}
