// b69_hash_fib
const std = @import("std");
fn fib_hash(key: i64, cap: i64) i64 {
    return @rem(@rem(key * 2654435761, cap) + cap, cap);
}
pub fn main() !void {
    const cap: i64 = 524288;
    const tab = try std.heap.page_allocator.alloc(i64, @intCast(cap));
    defer std.heap.page_allocator.free(tab);
    const t0 = std.time.nanoTimestamp();
    var cnt: i64 = 0;
    var j: i64 = 0;
    while (j < 500000) : (j += 1) {
        const h = fib_hash(j, cap);
        tab[@intCast(h)] += 1; cnt += 1;
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ cnt, t1 - t0 });
}
