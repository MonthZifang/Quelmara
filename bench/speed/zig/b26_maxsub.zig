// b26_maxsub —— Kadane 最大子数组
const std = @import("std");
pub fn main() !void {
    const n: i64 = 20000000;
    var seed: u64 = 42;
    const t0 = std.time.nanoTimestamp();
    var best: i64 = 0; var cur: i64 = 0;
    var i: i64 = 0;
    while (i < n) : (i += 1) {
        seed = (seed * 1103515245 + 12345) % 2147483648;
        const v = @as(i64, @intCast(seed % 201)) - 100;
        cur += v;
        if (cur < 0) cur = 0;
        if (cur > best) best = cur;
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ best, t1 - t0 });
}
