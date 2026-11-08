// b39_hash_open
const std = @import("std");
pub fn main() !void {
    const cap: i64 = 1048576;
    const keys = try std.heap.page_allocator.alloc(i64, @intCast(cap));
    const vals = try std.heap.page_allocator.alloc(i64, @intCast(cap));
    defer std.heap.page_allocator.free(keys);
    defer std.heap.page_allocator.free(vals);
    const t0 = std.time.nanoTimestamp();
    var j: i64 = 0;
    while (j < 500000) : (j += 1) {
        const h = @rem(j * 2654435761, cap);
        keys[@intCast(h)] = j; vals[@intCast(h)] = j * 2;
    }
    var found: i64 = 0;
    var k: i64 = 0;
    while (k < 500000) : (k += 1) {
        const h = @rem(k * 2654435761, cap);
        if (keys[@intCast(h)] == k) found += 1;
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ found, t1 - t0 });
}
