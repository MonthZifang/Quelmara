// b55_hash_chain
const std = @import("std");
pub fn main() !void {
    const cap: i64 = 262144;
    const buckets = try std.heap.page_allocator.alloc(i64, @intCast(cap));
    defer std.heap.page_allocator.free(buckets);
    const t0 = std.time.nanoTimestamp();
    var cnt: i64 = 0;
    var j: i64 = 0;
    while (j < 200000) : (j += 1) {
        const h = @rem(j * 2654435761, cap);
        buckets[@intCast(h)] += 1; cnt += 1;
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ cnt, t1 - t0 });
}
