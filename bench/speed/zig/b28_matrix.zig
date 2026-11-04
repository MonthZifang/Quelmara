// b28_matrix —— 数值：矩阵乘法 300x300
const std = @import("std");
pub fn main() !void {
    const n: usize = 300;
    const sz = n * n;
    var gpa = std.heap.GeneralPurposeAllocator(.{}){};
    defer _ = gpa.deinit();
    const alloc = gpa.allocator();
    var a = try alloc.alloc(i64, sz);
    defer alloc.free(a);
    var b = try alloc.alloc(i64, sz);
    defer alloc.free(b);
    var c = try alloc.alloc(i64, sz);
    defer alloc.free(c);
    var seed: u64 = 7;
    for (0..sz) |i| {
        seed = (seed *% 1103515245 +% 12345) % 2147483648;
        a[i] = @intCast(@rem(seed, 100));
        seed = (seed *% 1103515245 +% 12345) % 2147483648;
        b[i] = @intCast(@rem(seed, 100));
    }
    @memset(c, 0);
    const t0 = std.time.nanoTimestamp();
    for (0..n) |r| {
        for (0..n) |k| {
            const av = a[r * n + k];
            for (0..n) |j| {
                c[r * n + j] += av * b[k * n + j];
            }
        }
    }
    const t1 = std.time.nanoTimestamp();
    var chk: i64 = 0;
    for (0..sz) |i| chk = (chk + c[i]) % 1000000007;
    std.debug.print("{d}\nT\n{d}\n", .{ chk, t1 - t0 });
}
