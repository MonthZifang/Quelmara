// b38_prime
const std = @import("std");
fn is_prime(n: i64) i64 {
    if (n < 2) return 0;
    if (n == 2) return 1;
    if (@rem(n, 2) == 0) return 0;
    var d: i64 = 3;
    while (d * d <= n) : (d += 2) {
        if (@rem(n, d) == 0) return 0;
    }
    return 1;
}
pub fn main() !void {
    var cnt: i64 = 0;
    const t0 = std.time.nanoTimestamp();
    var i: i64 = 0;
    while (i < 100000) : (i += 1) cnt += is_prime(i);
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ cnt, t1 - t0 });
}
