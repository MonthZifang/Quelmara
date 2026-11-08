// b40_binary_search
const std = @import("std");
fn bsearch_impl(a: []i64, nn: i64, target: i64) i64 {
    var lo: i64 = 0; var hi: i64 = nn - 1;
    while (lo <= hi) {
        const mid = @divTrunc(lo + hi, 2);
        if (a[@intCast(mid)] == target) return mid;
        if (a[@intCast(mid)] < target) lo = mid + 1 else hi = mid - 1;
    }
    return -1;
}
pub fn main() !void {
    const n: i64 = 1000000;
    const a = try std.heap.page_allocator.alloc(i64, @intCast(n));
    defer std.heap.page_allocator.free(a);
    var i: i64 = 0;
    while (i < n) : (i += 1) a[@intCast(i)] = i * 2;
    const t0 = std.time.nanoTimestamp();
    var found: i64 = 0;
    var j: i64 = 0;
    while (j < 1000000) : (j += 1) {
        if (bsearch_impl(a, n, j * 2) >= 0) found += 1;
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ found, t1 - t0 });
}
