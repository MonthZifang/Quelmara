// b54_merge_sort
const std = @import("std");
fn merge(a: []i64, lo: i64, mid: i64, hi: i64, tmp: []i64) void {
    var i = lo; var j = mid; var k: i64 = 0;
    while (i < mid and j < hi) {
        tmp[@intCast(k)] = if (a[@intCast(i)] <= a[@intCast(j)]) a[@intCast(i)] else a[@intCast(j)];
        if (a[@intCast(i)] <= a[@intCast(j)]) i += 1 else j += 1;
        k += 1;
    }
    while (i < mid) : (i += 1) { tmp[@intCast(k)] = a[@intCast(i)]; k += 1; }
    while (j < hi) : (j += 1) { tmp[@intCast(k)] = a[@intCast(j)]; k += 1; }
    var x: i64 = 0;
    while (x < k) : (x += 1) a[@intCast(lo + x)] = tmp[@intCast(x)];
}
fn msort(a: []i64, lo: i64, hi: i64, tmp: []i64) void {
    if (hi - lo <= 1) return;
    const mid = @divTrunc(lo + hi, 2);
    msort(a, lo, mid, tmp);
    msort(a, mid, hi, tmp);
    merge(a, lo, mid, hi, tmp);
}
pub fn main() !void {
    const n: i64 = 100000;
    const a = try std.heap.page_allocator.alloc(i64, @intCast(n));
    const tmp = try std.heap.page_allocator.alloc(i64, @intCast(n));
    defer std.heap.page_allocator.free(a);
    defer std.heap.page_allocator.free(tmp);
    var seed: u64 = 12345;
    var i: i64 = 0;
    while (i < n) : (i += 1) { seed = (seed * 1103515245 + 12345) % 2147483648; a[@intCast(i)] = @intCast(seed % 1000000); }
    const t0 = std.time.nanoTimestamp();
    msort(a, 0, n, tmp);
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ a[0], t1 - t0 });
}
