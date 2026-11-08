// b6_hash —— 手写开放寻址哈希表
const std = @import("std");
pub fn main() !void {
    const cap: i64 = 1048576;
    const mask: i64 = cap - 1;
    const n: i64 = 300000;
    const t0 = std.time.nanoTimestamp();
    const kt = try std.heap.page_allocator.alloc(i64, @intCast(cap));
    const vt = try std.heap.page_allocator.alloc(i64, @intCast(cap));
    defer std.heap.page_allocator.free(kt);
    defer std.heap.page_allocator.free(vt);
    var i: i64 = 1;
    while (i <= n) : (i += 1) {
        const k: i64 = i * 3 + 1;
        var h: i64 = @rem(k * 2654435761, cap) & mask;
        while (kt[@intCast(h)] != 0) h = (h + 1) & mask;
        kt[@intCast(h)] = k;
        vt[@intCast(h)] = k * 2;
    }
    var s: i64 = 0;
    i = 1;
    while (i <= n) : (i += 1) {
        const k: i64 = i * 3 + 1;
        var h: i64 = @rem(k * 2654435761, cap) & mask;
        while (kt[@intCast(h)] != k) h = (h + 1) & mask;
        s += vt[@intCast(h)];
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ s, t1 - t0 });
}
