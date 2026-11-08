// b27_sieve —— 埃氏筛 5000 万
const std = @import("std");
pub fn main() !void {
    const n: i64 = 10000000;
    const c = try std.heap.page_allocator.alloc(u8, @intCast(n + 1));
    defer std.heap.page_allocator.free(c);
    var i: i64 = 0;
    while (i <= n) : (i += 1) c[@intCast(i)] = 1;
    c[0] = 0; c[1] = 0;
    const t0 = std.time.nanoTimestamp();
    var p: i64 = 2;
    while (p * p <= n) : (p += 1) {
        if (c[@intCast(p)] != 0) {
            var q = p * p;
            while (q <= n) : (q += p) c[@intCast(q)] = 0;
        }
    }
    var cnt: i64 = 0;
    i = 0;
    while (i <= n) : (i += 1) cnt += c[@intCast(i)];
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ cnt, t1 - t0 });
}
