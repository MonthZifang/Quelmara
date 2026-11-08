// b23_lcs —— DP 最长公共子序列
const std = @import("std");
pub fn main() !void {
    const n: i64 = 1500;
    const prev = try std.heap.page_allocator.alloc(i64, @intCast(n + 1));
    const cur = try std.heap.page_allocator.alloc(i64, @intCast(n + 1));
    defer std.heap.page_allocator.free(prev);
    defer std.heap.page_allocator.free(cur);
    const t0 = std.time.nanoTimestamp();
    var r: i64 = 1;
    while (r <= n) : (r += 1) {
        var c: i64 = 1;
        while (c <= n) : (c += 1) {
            const av: i64 = @rem(r * 7 + 3, 4);
            const bv: i64 = @rem(c * 11 + 5, 4);
            if (av == bv) cur[@intCast(c)] = prev[@intCast(c - 1)] + 1
            else cur[@intCast(c)] = if (prev[@intCast(c)] > cur[@intCast(c - 1)]) prev[@intCast(c)] else cur[@intCast(c - 1)];
        }
        c = 0;
        while (c <= n) : (c += 1) prev[@intCast(c)] = cur[@intCast(c)];
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ prev[@intCast(n)], t1 - t0 });
}
