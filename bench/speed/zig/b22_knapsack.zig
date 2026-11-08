// b22_knapsack —— 0/1 背包 DP
const std = @import("std");
pub fn main() !void {
    const n: i64 = 800; const cap: i64 = 800;
    const wt = try std.heap.page_allocator.alloc(i64, @intCast(n));
    const vl = try std.heap.page_allocator.alloc(i64, @intCast(n));
    defer std.heap.page_allocator.free(wt);
    defer std.heap.page_allocator.free(vl);
    var seed: u64 = 999;
    var i: i64 = 0;
    while (i < n) : (i += 1) {
        seed = (seed * 1103515245 + 12345) % 2147483648;
        wt[@intCast(i)] = @intCast(seed % 50 + 1);
        seed = (seed * 1103515245 + 12345) % 2147483648;
        vl[@intCast(i)] = @intCast(seed % 100 + 1);
    }
    const t0 = std.time.nanoTimestamp();
    const dp = try std.heap.page_allocator.alloc(i64, @intCast(cap + 1));
    defer std.heap.page_allocator.free(dp);
    var it: i64 = 0;
    while (it < n) : (it += 1) {
        var c: i64 = cap;
        while (c >= wt[@intCast(it)]) : (c -= 1) {
            const cand = dp[@intCast(c - wt[@intCast(it)])] + vl[@intCast(it)];
            if (cand > dp[@intCast(c)]) dp[@intCast(c)] = cand;
        }
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ dp[@intCast(cap)], t1 - t0 });
}
