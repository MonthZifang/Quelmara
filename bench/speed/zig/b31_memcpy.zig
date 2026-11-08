// b31_memcpy
const std = @import("std");
pub fn main() !void {
    const n: i64 = 12500000;
    const src = try std.heap.page_allocator.alloc(i64, @intCast(n));
    const dst = try std.heap.page_allocator.alloc(i64, @intCast(n));
    defer std.heap.page_allocator.free(src);
    defer std.heap.page_allocator.free(dst);
    var i: i64 = 0;
    while (i < n) : (i += 1) src[@intCast(i)] = i;
    const t0 = std.time.nanoTimestamp();
    i = 0;
    while (i < n) : (i += 1) dst[@intCast(i)] = src[@intCast(i)];
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ dst[@intCast(n - 1)], t1 - t0 });
}
