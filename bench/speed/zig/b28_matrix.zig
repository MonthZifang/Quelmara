// b28_matrix —— 矩阵乘法 300×300
const std = @import("std");
pub fn main() !void {
    const n: i64 = 300;
    const a = try std.heap.page_allocator.alloc(i64, @intCast(n * n));
    const b = try std.heap.page_allocator.alloc(i64, @intCast(n * n));
    const cc = try std.heap.page_allocator.alloc(i64, @intCast(n * n));
    defer std.heap.page_allocator.free(a);
    defer std.heap.page_allocator.free(b);
    defer std.heap.page_allocator.free(cc);
    var seed: u64 = 7;
    var i: i64 = 0;
    while (i < n * n) : (i += 1) {
        seed = (seed * 1103515245 + 12345) % 2147483648;
        a[@intCast(i)] = @intCast(seed % 100);
        seed = (seed * 1103515245 + 12345) % 2147483648;
        b[@intCast(i)] = @intCast(seed % 100);
    }
    const t0 = std.time.nanoTimestamp();
    var r: i64 = 0;
    while (r < n) : (r += 1) {
        var k: i64 = 0;
        while (k < n) : (k += 1) {
            const av = a[@intCast(r * n + k)];
            var j: i64 = 0;
            while (j < n) : (j += 1) cc[@intCast(r * n + j)] += av * b[@intCast(k * n + j)];
        }
    }
    const t1 = std.time.nanoTimestamp();
    var chk: i64 = 0;
    i = 0;
    while (i < n * n) : (i += 1) chk = @rem(chk + cc[@intCast(i)], 1000000007);
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ chk, t1 - t0 });
}
