// b58_rec_sum
const std = @import("std");
fn rec_sum(n: i64) i64 {
    if (n <= 0) return 0;
    return n + rec_sum(n - 1);
}
pub fn main() !void {
    const t0 = std.time.nanoTimestamp();
    var acc: i64 = 0;
    var i: i64 = 1;
    while (i <= 100) : (i += 1) acc += rec_sum(10000);
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ acc, t1 - t0 });
}
