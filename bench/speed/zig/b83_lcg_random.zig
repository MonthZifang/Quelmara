// b83_lcg_random
const std = @import("std");
pub fn main() !void {
    const t0 = std.time.nanoTimestamp();
    var seed: u64 = 12345;
    var acc: i64 = 0;
    var i: i64 = 0;
    while (i < 10000000) : (i += 1) {
        seed = (seed * 1103515245 + 12345) % 2147483648;
        acc += @intCast(seed % 100);
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ acc, t1 - t0 });
}
