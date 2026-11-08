// b37_swap
const std = @import("std");
pub fn main() !void {
    const n: i64 = 10000;
    const a = try std.heap.page_allocator.alloc(i64, @intCast(n));
    defer std.heap.page_allocator.free(a);
    var seed: u64 = 42;
    var i: i64 = 0;
    while (i < n) : (i += 1) {
        seed = (seed * 1103515245 + 12345) % 2147483648;
        a[@intCast(i)] = @intCast(seed % 100000);
    }
    const t0 = std.time.nanoTimestamp();
    var rnd: i64 = 0;
    while (rnd < 100) : (rnd += 1) {
        var j: i64 = 0;
        while (j < n - 1) : (j += 1) {
            if (a[@intCast(j)] > a[@intCast(j + 1)]) {
                const t = a[@intCast(j)]; a[@intCast(j)] = a[@intCast(j + 1)]; a[@intCast(j + 1)] = t;
            }
        }
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ a[0], t1 - t0 });
}
