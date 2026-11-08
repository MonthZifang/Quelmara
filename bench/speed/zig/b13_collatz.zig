// b13_collatz —— Collatz 序列长度累加
const std = @import("std");
fn clen(nn: i64) i64 {
    var n = nn; var c: i64 = 0;
    while (n != 1) {
        n = if (@rem(n, 2) == 0) @divTrunc(n, 2) else 3 * n + 1;
        c += 1;
    }
    return c;
}
pub fn main() !void {
    const t0 = std.time.nanoTimestamp();
    var best: i64 = 0; var bn: i64 = 0;
    var i: i64 = 1;
    while (i <= 300000) : (i += 1) {
        const c = clen(i);
        if (c > best) { best = c; bn = i; }
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ best * 10000000 + bn, t1 - t0 });
}
