// b7_sort —— 手写快排
const std = @import("std");
fn qsort_i64(a: []i64, lo: i64, hi: i64) void {
    if (lo >= hi) return;
    const p = a[@intCast(hi)];
    var i: i64 = lo;
    var j: i64 = lo;
    while (j < hi) : (j += 1) {
        if (a[@intCast(j)] < p) {
            const t = a[@intCast(i)]; a[@intCast(i)] = a[@intCast(j)]; a[@intCast(j)] = t;
            i += 1;
        }
    }
    const t2 = a[@intCast(i)]; a[@intCast(i)] = a[@intCast(hi)]; a[@intCast(hi)] = t2;
    qsort_i64(a, lo, i - 1);
    qsort_i64(a, i + 1, hi);
}
pub fn main() !void {
    const n: i64 = 200000;
    const t0 = std.time.nanoTimestamp();
    const v = try std.heap.page_allocator.alloc(i64, @intCast(n));
    defer std.heap.page_allocator.free(v);
    var x: i64 = 12345;
    var i: i64 = 0;
    while (i < n) : (i += 1) {
        x = (x * 1103515245 + 12345) & 2147483647;
        v[@intCast(i)] = x;
    }
    qsort_i64(v, 0, n - 1);
    var s: i64 = 0;
    i = 0;
    while (i < n) : (i += 1) s += @rem(v[@intCast(i)], 1000);
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\n{d}\n{d}\nT\n{d}\n", .{ v[0], v[@intCast(n - 1)], s, t1 - t0 });
}
