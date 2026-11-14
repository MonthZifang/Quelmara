// b53_thread_sim —— 确定性分段求和（非真实线程）
const std = @import("std");
fn work(start: i64, end: i64) i64 {
    var s: i64 = 0;
    var i = start;
    // v4.115 fairness audit: per-iteration doNotOptimizeAway stops closed-form
    // replacement of the sum (zero instructions, algorithm unchanged).
    while (i < end) : (i += 1) {
        s += i * 2 + 1;
        std.mem.doNotOptimizeAway(s);
    }
    return s;
}
pub fn main() !void {
    const n: i64 = 10000000;
    const t0 = std.time.nanoTimestamp();
    const a = work(0, n / 4);
    const b = work(n / 4, n / 2);
    const c = work(n / 2, 3 * n / 4);
    const d = work(3 * n / 4, n);
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ a + b + c + d, t1 - t0 });
}
