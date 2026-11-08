// b84_pair_swap
const std = @import("std");
pub fn main() !void {
    const n: i64 = 1000000;
    const keys = try std.heap.page_allocator.alloc(i64, @intCast(n));
    const vals = try std.heap.page_allocator.alloc(i64, @intCast(n));
    defer std.heap.page_allocator.free(keys);
    defer std.heap.page_allocator.free(vals);
    var i: i64 = 0;
    while (i < n) : (i += 1) { keys[@intCast(i)] = i; vals[@intCast(i)] = i * 2; }
    const t0 = std.time.nanoTimestamp();
    var j: i64 = 0;
    while (j < n) : (j += 1) {
        const kk = keys[@intCast(j)]; const v = vals[@intCast(j)];
        keys[@intCast(j)] = v; vals[@intCast(j)] = kk;
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ keys[0] + vals[0], t1 - t0 });
}
