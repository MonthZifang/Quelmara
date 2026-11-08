// b61_cache_scan
const std = @import("std");
pub fn main() !void {
    const n: i64 = 1000000;
    const a = try std.heap.page_allocator.alloc(i64, @intCast(n));
    defer std.heap.page_allocator.free(a);
    var i: i64 = 0;
    while (i < n) : (i += 1) a[@intCast(i)] = i;
    const t0 = std.time.nanoTimestamp();
    var acc: i64 = 0;
    var j: i64 = 0;
    while (j < 10) : (j += 1) {
        var k: i64 = 0;
        while (k < n) : (k += 1) acc += a[@intCast(k)];
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ acc, t1 - t0 });
}
