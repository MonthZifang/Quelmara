// b13_collatz —— 分支预测 + 整数除法：Collatz 1..30 万
// 与 C / quelmara 版算法逐字等价，只打印"结果 + T + 纳秒耗时"。
use std::time::Instant;

fn now_ns(t: &Instant) -> i64 {
    t.elapsed().as_nanos() as i64
}


fn clen(n0: i64) -> i64 {
    let mut n = n0; let mut c = 0i64;
    while n != 1 {
        n = if n % 2 == 0 { n / 2 } else { 3 * n + 1 };
        c += 1;
    }
    c
}
fn main() {
    let t0 = Instant::now();
    let mut best = 0i64; let mut bn = 0i64;
    for i in 1..=300000i64 {
        let c = clen(i);
        if c > best { best = c; bn = i; }
    }
    let el = now_ns(&t0);
    println!("{}", best * 10000000 + bn); println!("T"); println!("{}", el);
}
