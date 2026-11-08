// b70_lin_search
const std = @import("std");
pub fn main() !void {
    const n: i64 = 1000;
    const a = try std.heap.page_allocator.alloc(i64, @intCast(n));
    defer std.heap.page_allocator.free(a);
    var i: i64 = 0;
    while (i < n) : (i += 1) a[@intCast(i)] = i * 3 + 7;
    const t0 = std.time.nanoTimestamp();
    var found: i64 = 0;
    var j: i64 = 0;
    while (j < 1000000) : (j += 1) {
        const target = @rem(j * 37 + 11, 3000);
        var k: i64 = 0;
        while (k < n) : (k += 1) { if (a[@intCast(k)] == target) found += 1; }
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ found, t1 - t0 });
}
