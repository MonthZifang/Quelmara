// b81_bit_reverse
const std = @import("std");
fn bitrev(x0: i64) i64 {
    var v = x0; var r: i64 = 0;
    var i: i64 = 0;
    while (i < 32) : (i += 1) { r = (r << 1) | (v & 1); v >>= 1; }
    return r;
}
pub fn main() !void {
    const t0 = std.time.nanoTimestamp();
    var acc: i64 = 0;
    var j: i64 = 0;
    while (j < 1000000) : (j += 1) acc ^= bitrev(j);
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ acc, t1 - t0 });
}
