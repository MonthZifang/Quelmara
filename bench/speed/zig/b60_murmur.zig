// b60_murmur —— 用无符号运算复刻 C 的 int64 位操作：
// C 的 `>>` 在有符号上是算术（符号扩展）右移，且 `<<`/`*` 在 int64 上回绕；
// 为避免 Zig 在已知循环趟数时对有符号溢出的误优化，这里全部走 u64（回绕），
// 并用 ashr 手动做符号扩展右移，保证与 C 的 2 补码位模式逐位一致。
const std = @import("std");
fn ashr(x: u64) u64 {
    const sign = 0 -% (x >> 63); // x 最高位为 1 时全 1，否则全 0
    return (x >> 51) | (sign << 13);
}
fn murmur(h: i64, k: i64) i64 {
    var key: u64 = @bitCast(k);
    key *%= @as(u64, @bitCast(@as(i64, -862048943)));
    key = (key << 13) | (ashr(key) & 0x1FFFFFFFFFFF);
    key *%= @as(u64, @bitCast(@as(i64, -862048943)));
    var hh: u64 = @bitCast(h);
    hh ^= key;
    hh = (hh << 13) | (ashr(hh) & 0x1FFFFFFFFFFF);
    return @bitCast(hh *% 5 +% 1);
}
pub fn main() !void {
    const t0 = std.time.nanoTimestamp();
    var acc: i64 = 0;
    var i: i64 = 0;
    while (i < 1000000) : (i += 1) acc = murmur(acc, i);
    const t1 = std.time.nanoTimestamp();
    try std.io.getStdOut().writer().print("{d}\nT\n{d}\n", .{ acc, t1 - t0 });
}
