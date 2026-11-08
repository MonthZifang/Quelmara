// b86_matrix_diag
const std = @import("std");
pub fn main() !void {
    const n: i64 = 1000; const sz: i64 = n * n;
    const a = try std.heap.page_allocator.alloc(i64, @intCast(sz));
    defer std.heap.page_allocator.free(a);
    var i: i64 = 0;
    while (i < sz) : (i += 1) a[@intCast(i)] = @rem(i * 7 + 3, 100);
    const t0 = std.time.nanoTimestamp();
    var sum: i64 = 0;
    var r: i64 = 0;
    while (r < n) : (r += 1) sum += a[@intCast(r * n + r)];
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ sum, t1 - t0 });
}
