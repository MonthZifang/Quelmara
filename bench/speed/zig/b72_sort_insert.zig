// b72_sort_insert
const std = @import("std");
pub fn main() !void {
    const n: i64 = 10000;
    const a = try std.heap.page_allocator.alloc(i64, @intCast(n));
    defer std.heap.page_allocator.free(a);
    var seed: u64 = 777;
    var i: i64 = 0;
    while (i < n) : (i += 1) { seed = (seed * 1103515245 + 12345) % 2147483648; a[@intCast(i)] = @intCast(seed % 100000); }
    const t0 = std.time.nanoTimestamp();
    var x: i64 = 1;
    while (x < n) : (x += 1) {
        const key = a[@intCast(x)]; var y = x - 1;
        while (y >= 0 and a[@intCast(y)] > key) { a[@intCast(y + 1)] = a[@intCast(y)]; y -= 1; }
        a[@intCast(y + 1)] = key;
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ a[0], t1 - t0 });
}
