// b76_io_line
const std = @import("std");
pub fn main() !void {
    const n: i64 = 1000000;
    const lines = try std.heap.page_allocator.alloc(i64, @intCast(n));
    defer std.heap.page_allocator.free(lines);
    var i: i64 = 0;
    while (i < n) : (i += 1) lines[@intCast(i)] = i * 7 + 3;
    const t0 = std.time.nanoTimestamp();
    var sum: i64 = 0;
    var j: i64 = 0;
    while (j < n) : (j += 1) sum += @rem(lines[@intCast(j)], 100);
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ sum, t1 - t0 });
}
