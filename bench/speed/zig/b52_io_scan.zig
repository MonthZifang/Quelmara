// b52_io_scan
const std = @import("std");
pub fn main() !void {
    const n: i64 = 1000000;
    const buf = try std.heap.page_allocator.alloc(i64, @intCast(n));
    defer std.heap.page_allocator.free(buf);
    var i: i64 = 0;
    while (i < n) : (i += 1) buf[@intCast(i)] = i * 3 + 1;
    const t0 = std.time.nanoTimestamp();
    var sum: i64 = 0;
    var j: i64 = 0;
    while (j < n) : (j += 1) sum += buf[@intCast(j)];
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ sum, t1 - t0 });
}
