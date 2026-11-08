// b59_mat_vec
const std = @import("std");
pub fn main() !void {
    const n: i64 = 500; const sz: i64 = n * n;
    const mat = try std.heap.page_allocator.alloc(i64, @intCast(sz));
    const vec = try std.heap.page_allocator.alloc(i64, @intCast(n));
    defer std.heap.page_allocator.free(mat);
    defer std.heap.page_allocator.free(vec);
    var i: i64 = 0;
    while (i < sz) : (i += 1) mat[@intCast(i)] = @rem(i * 7 + 3, 100);
    var j: i64 = 0;
    while (j < n) : (j += 1) vec[@intCast(j)] = @rem(j * 13 + 1, 100);
    const t0 = std.time.nanoTimestamp();
    var total: i64 = 0;
    var r: i64 = 0;
    while (r < n) : (r += 1) {
        var s: i64 = 0;
        var c: i64 = 0;
        while (c < n) : (c += 1) s += mat[@intCast(r * n + c)] * vec[@intCast(c)];
        total += s;
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ total, t1 - t0 });
}
