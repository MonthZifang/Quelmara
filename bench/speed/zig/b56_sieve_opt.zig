// b56_sieve_opt
const std = @import("std");
pub fn main() !void {
    const n: i64 = 2000000;
    const flags = try std.heap.page_allocator.alloc(i64, @intCast(n + 1));
    defer std.heap.page_allocator.free(flags);
    var i: i64 = 0;
    while (i <= n) : (i += 1) flags[@intCast(i)] = 1;
    flags[0] = 0; flags[1] = 0;
    const t0 = std.time.nanoTimestamp();
    var p: i64 = 2;
    while (p * p <= n) : (p += 1) {
        if (flags[@intCast(p)] != 0) {
            var q = p * p;
            while (q <= n) : (q += p) flags[@intCast(q)] = 0;
        }
    }
    var cnt: i64 = 0;
    var kk: i64 = 2;
    while (kk <= n) : (kk += 1) { if (flags[@intCast(kk)] != 0) cnt += 1; }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ cnt, t1 - t0 });
}
