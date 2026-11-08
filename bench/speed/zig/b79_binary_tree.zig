// b79_binary_tree
const std = @import("std");
pub fn main() !void {
    const keys = try std.heap.page_allocator.alloc(i64, 50000);
    defer std.heap.page_allocator.free(keys);
    var n: i64 = 0;
    var seed: u64 = 42;
    const t0 = std.time.nanoTimestamp();
    var i: i64 = 0;
    while (i < 50000) : (i += 1) {
        seed = (seed * 1103515245 + 12345) % 2147483648;
        const key: i64 = @intCast(seed % 100000);
        var pos = n;
        var j: i64 = 0;
        while (j < n) : (j += 1) { if (keys[@intCast(j)] > key) { pos = j; break; } }
        var k: i64 = n;
        while (k > pos) : (k -= 1) keys[@intCast(k)] = keys[@intCast(k - 1)];
        keys[@intCast(pos)] = key; n += 1;
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ keys[0], t1 - t0 });
}
