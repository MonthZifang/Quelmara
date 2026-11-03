// b12_gcd —— 整数：3000 万次辗转相除
// 与 C / quelmara 版算法逐字等价，只打印"结果 + T + 纳秒耗时"。
use std::time::Instant;

fn now_ns(t: &Instant) -> i64 {
    t.elapsed().as_nanos() as i64
}


fn gcd(mut a: i64, mut b: i64) -> i64 {
    while b != 0 { let t = b; b = a % b; a = t; }
    a
}
fn main() {
    let n = 30000000i64;
    let t0 = Instant::now();
    let mut s = 0i64;
    for i in 1..=n { s = s.wrapping_add(gcd(i, 1000000 - i)); }
    let el = now_ns(&t0);
    println!("{}", s); println!("T"); println!("{}", el);
}
