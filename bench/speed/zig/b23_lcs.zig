// b23_lcs —— DP：最长公共子序列 1500x1500
const std = @import("std");
pub fn main() !void {
    const n: usize = 1500;
    var gpa = std.heap.GeneralPurposeAllocator(.{}){};
    defer _ = gpa.deinit();
    const alloc = gpa.allocator();
    var prev = try alloc.alloc(i64, n + 1);
    defer alloc.free(prev);
    var cur = try alloc.alloc(i64, n + 1);
    defer alloc.free(cur);
    @memset(prev, 0);
    @memset(cur, 0);
    const t0 = std.time.nanoTimestamp();
    var r: usize = 1;
    while (r <= n) : (r += 1) {
        var c: usize = 1;
        while (c <= n) : (c += 1) {
            const av: i64 = @intCast((r * 7 + 3) % 4);
            const bv: i64 = @intCast((c * 11 + 5) % 4);
            if (av == bv) {
                cur[c] = prev[c - 1] + 1;
            } else {
                cur[c] = if (prev[c] > cur[c - 1]) prev[c] else cur[c - 1];
            }
        }
        for (0..n + 1) |i| prev[i] = cur[i];
    }
    const t1 = std.time.nanoTimestamp();
    std.debug.print("{d}\nT\n{d}\n", .{ prev[n], t1 - t0 });
}
