// b34_bitops
const std = @import("std");
pub fn main() !void {
    var acc: i64 = 0;
    const t0 = std.time.nanoTimestamp();
    var i: i64 = 0;
    while (i < 20000000) : (i += 1) acc += ((i ^ (i << 3)) & 0xFFFF) + ((i >> 2) | (i << 5));
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ acc, t1 - t0 });
}
