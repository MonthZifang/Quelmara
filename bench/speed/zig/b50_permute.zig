// b50_permute
const std = @import("std");
fn perm(arr: []i64, k: i64, nn: i64, acc: i64) i64 {
    if (k == nn) {
        var h: i64 = 0;
        var i: i64 = 0;
        while (i < nn) : (i += 1) h = h * 31 + arr[@intCast(i)];
        return acc + @rem(h, 1000003);
    }
    var s = acc;
    var i: i64 = k;
    while (i < nn) : (i += 1) {
        const t = arr[@intCast(k)]; arr[@intCast(k)] = arr[@intCast(i)]; arr[@intCast(i)] = t;
        s = perm(arr, k + 1, nn, s);
        const t2 = arr[@intCast(k)]; arr[@intCast(k)] = arr[@intCast(i)]; arr[@intCast(i)] = t2;
    }
    return s;
}
pub fn main() !void {
    var a: [10]i64 = [_]i64{0} ** 10;
    var i: i64 = 0;
    while (i < 10) : (i += 1) a[@intCast(i)] = i + 1;
    const t0 = std.time.nanoTimestamp();
    const r = perm(&a, 0, 10, 0);
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ r, t1 - t0 });
}
