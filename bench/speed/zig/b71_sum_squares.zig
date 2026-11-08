// b71_sum_squares
const std = @import("std");
pub fn main() !void {
    const t0 = std.time.nanoTimestamp();
    var acc: i64 = 0;
    var i: i64 = 1;
    while (i <= 1000000) : (i += 1) acc += i * i;
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ @rem(acc, 1000003), t1 - t0 });
}
