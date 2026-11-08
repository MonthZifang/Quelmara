// b4_array —— 数组写入 + 顺序遍历 + 跨步遍历（200 万元素）
const std = @import("std");
pub fn main() !void {
    const n: i64 = 2000000;
    const t0 = std.time.nanoTimestamp();
    const v = try std.heap.page_allocator.alloc(i64, @intCast(n));
    defer std.heap.page_allocator.free(v);
    var i: i64 = 0;
    while (i < n) : (i += 1) v[@intCast(i)] = i * 3 + 1;
    var s: i64 = 0;
    i = 0;
    while (i < n) : (i += 1) s += v[@intCast(i)];
    var t: i64 = 0;
    i = 0;
    while (i < n) : (i += 7) t += v[@intCast(i)];
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\n{d}\nT\n{d}\n", .{ s, t, t1 - t0 });
}
