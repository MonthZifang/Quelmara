// b46_strcat
const std = @import("std");
pub fn main() !void {
    const t0 = std.time.nanoTimestamp();
    var acc: i64 = 0;
    var i: i64 = 0;
    while (i < 100000) : (i += 1) {
        var s: [64]u8 = undefined;
        const n = std.fmt.bufPrint(&s, "{s} {s} {s}", .{ "hello", "world", "12345" }) catch unreachable;
        acc += @intCast(n.len);
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ acc, t1 - t0 });
}
