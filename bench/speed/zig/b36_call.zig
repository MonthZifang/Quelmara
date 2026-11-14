// b36_call
const std = @import("std");
fn add3(a: i64, b: i64, c: i64) i64 { return a + b + c; }
pub fn main() !void {
    var acc: i64 = 0;
    const t0 = std.time.nanoTimestamp();
    var i: i64 = 0;
    // v4.115 fairness audit: per-iteration doNotOptimizeAway stops Zig from
    // replacing the loop by a closed form (zero instructions, portable).
    while (i < 10000000) : (i += 1) {
        acc = add3(acc, i, 1);
        std.mem.doNotOptimizeAway(acc);
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ acc, t1 - t0 });
}
