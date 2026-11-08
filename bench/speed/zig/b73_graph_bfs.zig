// b73_graph_bfs
const std = @import("std");
pub fn main() !void {
    const n: i64 = 1000;
    const adj = try std.heap.page_allocator.alloc(i64, @intCast(n * n));
    defer std.heap.page_allocator.free(adj);
    var seed: u64 = 55;
    var e: i64 = 0;
    while (e < 5000) : (e += 1) {
        seed = (seed * 1103515245 + 12345) % 2147483648; const u: i64 = @intCast(seed % @as(u64, @intCast(n)));
        seed = (seed * 1103515245 + 12345) % 2147483648; const v: i64 = @intCast(seed % @as(u64, @intCast(n)));
        adj[@intCast(u * n + v)] = 1;
    }
    const t0 = std.time.nanoTimestamp();
    const visited = try std.heap.page_allocator.alloc(i64, @intCast(n));
    const queue = try std.heap.page_allocator.alloc(i64, @intCast(n));
    defer std.heap.page_allocator.free(visited);
    defer std.heap.page_allocator.free(queue);
    var front: i64 = 0; var back: i64 = 0;
    queue[@intCast(back)] = 0; back += 1; visited[0] = 1;
    var cnt: i64 = 0;
    while (front < back) {
        const u = queue[@intCast(front)]; front += 1; cnt += 1;
        var v: i64 = 0;
        while (v < n) : (v += 1) {
            if (adj[@intCast(u * n + v)] != 0 and visited[@intCast(v)] == 0) { visited[@intCast(v)] = 1; queue[@intCast(back)] = v; back += 1; }
        }
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ cnt, t1 - t0 });
}
