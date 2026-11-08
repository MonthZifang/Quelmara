// b66_integrate
const std = @import("std");
fn f(x: i64) i64 { return @rem(x * x + 3 * x + 5, 1000003); }
pub fn main() !void {
    const t0 = std.time.nanoTimestamp();
    var acc: i64 = 0;
    var i: i64 = 0;
    while (i < 1000000) : (i += 1) acc = @rem(acc + f(i), 1000003);
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ acc, t1 - t0 });
}
