// b71_sum_squares
const std = @import("std");
pub fn main() !void {
    const t0 = std.time.nanoTimestamp();
    var acc: i64 = 0;
    var i: i64 = 1;
    // v4.115 fairness audit: per-iteration doNotOptimizeAway stops closed-form
    // replacement of the sum (zero instructions, algorithm unchanged).
    while (i <= 1000000) : (i += 1) {
        acc += i * i;
        std.mem.doNotOptimizeAway(acc);
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ @rem(acc, 1000003), t1 - t0 });
}
