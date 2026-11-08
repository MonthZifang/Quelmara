// b68_bit_matrix
const std = @import("std");
pub fn main() !void {
    const n: i64 = 256; const sz: i64 = n * n;
    const a = try std.heap.page_allocator.alloc(i64, @intCast(sz));
    const b = try std.heap.page_allocator.alloc(i64, @intCast(sz));
    defer std.heap.page_allocator.free(a);
    defer std.heap.page_allocator.free(b);
    var i: i64 = 0;
    while (i < sz) : (i += 1) a[@intCast(i)] = @rem(i, 2);
    const t0 = std.time.nanoTimestamp();
    var r: i64 = 0;
    while (r < n) : (r += 1) {
        var c: i64 = 0;
        while (c < n) : (c += 1) b[@intCast(r * n + c)] = a[@intCast(c * n + (n - 1 - r))];
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ b[0], t1 - t0 });
}
