// b78_sum_digits
const std = @import("std");
fn digit_sum(n0: i64) i64 {
    var n = n0; var s: i64 = 0;
    while (n > 0) : (n = @divTrunc(n, 10)) s += @rem(n, 10);
    return s;
}
pub fn main() !void {
    const t0 = std.time.nanoTimestamp();
    var acc: i64 = 0;
    var i: i64 = 0;
    while (i < 1000000) : (i += 1) acc += digit_sum(i);
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ acc, t1 - t0 });
}
