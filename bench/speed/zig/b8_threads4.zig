// b8_threads4 —— 同总量拆 4 段（确定性结果，非真实线程）
const std = @import("std");
fn run(n: i64) i64 {
    var acc: i64 = 0;
    var i: i64 = 0;
    while (i < n) : (i += 1) acc += @rem(i * 7, 13);
    return acc;
}
pub fn main() !void {
    const t0 = std.time.nanoTimestamp();
    const a = run(40000000);
    const b = run(40000000);
    const c = run(40000000);
    const d = run(40000000);
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ a + b + c + d, t1 - t0 });
}
