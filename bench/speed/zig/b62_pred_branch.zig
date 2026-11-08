// b62_pred_branch
const std = @import("std");
pub fn main() !void {
    const t0 = std.time.nanoTimestamp();
    var acc: i64 = 0;
    var i: i64 = 0;
    while (i < 5000000) : (i += 1) {
        if (@rem(i * 7 + 3, 5) < 2) acc += 1 else acc -= 1;
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ acc, t1 - t0 });
}
