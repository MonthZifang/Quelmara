// b77_rec_fib
const std = @import("std");
fn fib(n: i64) i64 {
    if (n <= 1) return n;
    return fib(n - 1) + fib(n - 2);
}
pub fn main() !void {
    const t0 = std.time.nanoTimestamp();
    const r = fib(25);
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ r, t1 - t0 });
}
