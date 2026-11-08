// b33_startup
const std = @import("std");
fn init() i64 {
    var s: i64 = 0;
    var i: i64 = 0;
    while (i < 1000) : (i += 1) s += i;
    return s;
}
pub fn main() !void {
    const t0 = std.time.nanoTimestamp();
    const a = init();
    const b = init();
    const c = init();
    const d = init();
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ a + b + c + d, t1 - t0 });
}
