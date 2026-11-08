// b44_stack_sim
const std = @import("std");
pub fn main() !void {
    const st = try std.heap.page_allocator.alloc(i64, 1000000);
    defer std.heap.page_allocator.free(st);
    var top: i64 = 0;
    const t0 = std.time.nanoTimestamp();
    var i: i64 = 0;
    while (i < 1000000) : (i += 1) {
        st[@intCast(top)] = i; top += 1;
        if (@rem(i, 3) == 0 and top > 0) st[@intCast(top - 1)] += 1;
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ st[@intCast(top - 1)], t1 - t0 });
}
