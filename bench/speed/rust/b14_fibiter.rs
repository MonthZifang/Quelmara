// b14_fibiter —— 迭代 fib 5000 万
// 与 C / quelmara 版算法逐字等价，只打印"结果 + T + 纳秒耗时"。
use std::time::Instant;

fn now_ns(t: &Instant) -> i64 {
    t.elapsed().as_nanos() as i64
}


fn main() {
    let n = 50000000i64;
    let t0 = Instant::now();
    let mut a = 0i64; let mut b = 1i64;
    for _ in 0..n {
        let t = a + b;
        a = b;
        b = t % 1000000007;
    }
    let el = now_ns(&t0);
    println!("{}", a); println!("T"); println!("{}", el);
}
