// b49_floyd
const std = @import("std");
pub fn main() !void {
    const n: i64 = 100; const sz: i64 = n * n;
    const dist = try std.heap.page_allocator.alloc(i64, @intCast(sz));
    defer std.heap.page_allocator.free(dist);
    var i: i64 = 0;
    while (i < sz) : (i += 1) dist[@intCast(i)] = 999999;
    var kk: i64 = 0;
    while (kk < n) : (kk += 1) dist[@intCast(kk * n + kk)] = 0;
    var seed: u64 = 7;
    var e: i64 = 0;
    while (e < 300) : (e += 1) {
        seed = (seed * 1103515245 + 12345) % 2147483648; const u: i64 = @intCast(seed % @as(u64, @intCast(n)));
        seed = (seed * 1103515245 + 12345) % 2147483648; const v: i64 = @intCast(seed % @as(u64, @intCast(n)));
        seed = (seed * 1103515245 + 12345) % 2147483648; const w = @as(i64, @intCast(seed % 100 + 1));
        dist[@intCast(u * n + v)] = w;
    }
    const t0 = std.time.nanoTimestamp();
    var a: i64 = 0;
    while (a < n) : (a += 1) {
        var b: i64 = 0;
        while (b < n) : (b += 1) {
            var c: i64 = 0;
            while (c < n) : (c += 1) {
                const d1 = dist[@intCast(b * n + c)];
                const d2 = dist[@intCast(b * n + a)] + dist[@intCast(a * n + c)];
                if (d2 < d1) dist[@intCast(b * n + c)] = d2;
            }
        }
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ dist[@intCast(1)], t1 - t0 });
}
