// b5_string —— 20 万次 int→str→int
const std = @import("std");
pub fn main() !void {
    const n: i64 = 500000;
    const t0 = std.time.nanoTimestamp();
    var acc: i64 = 0;
    var i: i64 = 0;
    while (i < n) : (i += 1) {
        var buf: [24]u8 = undefined;
        const len = std.fmt.bufPrint(&buf, "{d}", .{i}) catch unreachable;
        acc += @intCast(len.len);
        acc += std.fmt.parseInt(i64, std.mem.sliceTo(&buf, 0), 10) catch unreachable;
    }
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ acc, t1 - t0 });
}
