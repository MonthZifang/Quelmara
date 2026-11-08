// b48_sum_matrix
const std = @import("std");
pub fn main() !void {
    const n: i64 = 500; const sz: i64 = n * n;
    const a = try std.heap.page_allocator.alloc(i64, @intCast(sz));
    defer std.heap.page_allocator.free(a);
    var i: i64 = 0;
    while (i < sz) : (i += 1) a[@intCast(i)] = i;
    const t0 = std.time.nanoTimestamp();
    var total: i64 = 0;
    var r: i64 = 0;
    while (r < n) : (r += 1) {
        var s: i64 = 0;
        var c: i64 = 0;
        while (c < n) : (c += 1) s += a[@intCast(r * n + c)];
        total += s;
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ total, t1 - t0 });
}
