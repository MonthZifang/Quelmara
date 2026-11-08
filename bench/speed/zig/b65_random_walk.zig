// b65_random_walk
const std = @import("std");
pub fn main() !void {
    const t0 = std.time.nanoTimestamp();
    var x: i64 = 0; var y: i64 = 0;
    var seed: u64 = 12345;
    var i: i64 = 0;
    while (i < 2000000) : (i += 1) {
        seed = (seed * 1103515245 + 12345) % 2147483648;
        const d = @as(i64, @intCast(seed % 4));
        if (d == 0) x += 1 else if (d == 1) x -= 1 else if (d == 2) y += 1 else y -= 1;
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ x * 1000000 + y, t1 - t0 });
}
