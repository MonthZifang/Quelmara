// b57_pow_mod
const std = @import("std");
fn pow_mod(base: i64, exp: i64, mod: i64) i64 {
    var result: i64 = 1; var b = @rem(base, mod);
    var e = exp;
    while (e > 0) {
        if (@rem(e, 2) == 1) result = @rem(result * b, mod);
        b = @rem(b * b, mod); e = @divTrunc(e, 2);
    }
    return result;
}
pub fn main() !void {
    const t0 = std.time.nanoTimestamp();
    var acc: i64 = 0;
    var i: i64 = 1;
    while (i <= 1000000) : (i += 1) acc = @rem(acc + pow_mod(i, i, 1000003), 1000003);
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ acc, t1 - t0 });
}
