// b11_nqueens —— N 皇后(8)
const std = @import("std");
fn solve(col: []i64, n: i64, r: i64) i64 {
    if (r == n) return 1;
    var cnt: i64 = 0;
    var c: i64 = 0;
    while (c < n) : (c += 1) {
        var ok: i64 = 1;
        var k: i64 = 0;
        while (k < r) : (k += 1) {
            const cc = col[@intCast(k)];
            if (cc == c) ok = 0;
            const d = cc - c;
            if (d == k - r or d == r - k) ok = 0;
        }
        if (ok == 1) { col[@intCast(r)] = c; cnt += solve(col, n, r + 1); }
    }
    return cnt;
}
pub fn main() !void {
    const n: i64 = 8;
    var col: [8]i64 = [_]i64{0} ** 8;
    const t0 = std.time.nanoTimestamp();
    var total: i64 = 0;
    var rep: i64 = 0;
    while (rep < 2000) : (rep += 1) total += solve(&col, n, 0);
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ total, t1 - t0 });
}
