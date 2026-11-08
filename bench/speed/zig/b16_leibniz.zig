// b16_leibniz —— 浮点 Leibniz 级数 π
const std = @import("std");
pub fn main() !void {
    const n: i64 = 20000000;
    const t0 = std.time.nanoTimestamp();
    var s: f64 = 0.0;
    var i: i64 = 0;
    while (i < n) : (i += 1) {
        const d: f64 = @floatFromInt(2 * i + 1);
        if (@rem(i, 2) == 0) s += 1.0 / d else s -= 1.0 / d;
    }
    const pi = s * 4.0;
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d:.6}\nT\n{d}\n", .{ pi, t1 - t0 });
}
