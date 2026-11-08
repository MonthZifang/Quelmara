// b87_memcopy_big —— 内存 mem_copy 大块
const std = @import("std");
pub fn main() !void {
    const n: i64 = 12500000;
    const src = try std.heap.page_allocator.alloc(i64, @intCast(n));
    const dst = try std.heap.page_allocator.alloc(i64, @intCast(n));
    defer std.heap.page_allocator.free(src);
    defer std.heap.page_allocator.free(dst);
    var i: i64 = 0;
    while (i < n) : (i += 1) src[@intCast(i)] = i * 7 + 1;
    const t0 = std.time.nanoTimestamp();
    i = 0;
    while (i < n) : (i += 1) dst[@intCast(i)] = src[@intCast(i)];
    const t1 = std.time.nanoTimestamp();
    const chk = dst[0] + dst[6250000] + dst[@intCast(n - 1)];
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ chk, t1 - t0 });
}
