// b75_fib_matrix
const std = @import("std");
pub fn main() !void {
    const t0 = std.time.nanoTimestamp();
    var a0: i64 = 1; var a1: i64 = 1; var a2: i64 = 1; var a3: i64 = 0;
    var n: i64 = 1000;
    while (n > 0) {
        if (@rem(n, 2) == 1) {
            const t = @rem(a0 * a1 + a1 * a3, 1000003);
            const u = @rem(a0 * a2 + a1 * a3, 1000003);
            const v = @rem(a2 * a1 + a3 * a3, 1000003);
            const w = @rem(a2 * a1 + a3 * a3, 1000003);
            a0 = t; a1 = u; a2 = v; a3 = w;
        }
        const b0 = @rem(a0 * a0 + a1 * a2, 1000003);
        const b1 = @rem(a0 * a1 + a1 * a3, 1000003);
        const b2 = @rem(a2 * a0 + a3 * a2, 1000003);
        const b3 = @rem(a2 * a1 + a3 * a3, 1000003);
        a0 = b0; a1 = b1; a2 = b2; a3 = b3;
        n = @divTrunc(n, 2);
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ a1, t1 - t0 });
}
