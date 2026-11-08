// b82_array_fill
const std = @import("std");
pub fn main() !void {
    const n: i64 = 5000000;
    const a = try std.heap.page_allocator.alloc(i64, @intCast(n));
    defer std.heap.page_allocator.free(a);
    const t0 = std.time.nanoTimestamp();
    var i: i64 = 0;
    while (i < n) : (i += 1) a[@intCast(i)] = i * 2 + 1;
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ a[@intCast(n - 1)], t1 - t0 });
}
