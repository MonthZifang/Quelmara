// b18_insertion —— 插入排序 8 万元素
const std = @import("std");
pub fn main() !void {
    const n: i64 = 80000;
    const a = try std.heap.page_allocator.alloc(i64, @intCast(n));
    defer std.heap.page_allocator.free(a);
    var seed: u64 = 12345;
    var i: i64 = 0;
    while (i < n) : (i += 1) {
        seed = (seed * 1103515245 + 12345) % 2147483648;
        a[@intCast(i)] = @intCast(seed % 100000);
    }
    const t0 = std.time.nanoTimestamp();
    var x: i64 = 1;
    while (x < n) : (x += 1) {
        const key = a[@intCast(x)];
        var y: i64 = x - 1;
        while (y >= 0 and a[@intCast(y)] > key) {
            a[@intCast(y + 1)] = a[@intCast(y)];
            y -= 1;
        }
        a[@intCast(y + 1)] = key;
    }
    const t1 = std.time.nanoTimestamp();
    var chk: i64 = 0;
    i = 0;
    while (i < n) : (i += 1) chk = @rem(chk + a[@intCast(i)] * (i + 1), 1000000007);
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ chk, t1 - t0 });
}
