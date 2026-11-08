// b10_ackermann —— Ackermann(2,8)
const std = @import("std");
fn ack(m: i64, n: i64) i64 {
    if (m == 0) return n + 1;
    if (n == 0) return ack(m - 1, 1);
    return ack(m - 1, ack(m, n - 1));
}
pub fn main() !void {
    const t0 = std.time.nanoTimestamp();
    const r = ack(2, 8);
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ r, t1 - t0 });
}
