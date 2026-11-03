// b10_ackermann —— 递归：Ackermann(2,8)
// 与 C / quelmara 版算法逐字等价，只打印"结果 + T + 纳秒耗时"。
use std::time::Instant;

fn now_ns(t: &Instant) -> i64 {
    t.elapsed().as_nanos() as i64
}


fn ack(m: i64, n: i64) -> i64 {
    if m == 0 { return n + 1; }
    if n == 0 { return ack(m - 1, 1); }
    ack(m - 1, ack(m, n - 1))
}
fn main() {
    let t0 = Instant::now();
    let r = ack(2, 8);
    let el = now_ns(&t0);
    println!("{}", r); println!("T"); println!("{}", el);
}
