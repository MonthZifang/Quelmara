// b16_leibniz —— 浮点：Leibniz 级数 pi，2000 万项
// 与 C / quelmara 版算法逐字等价，只打印"结果 + T + 纳秒耗时"。
use std::time::Instant;

fn now_ns(t: &Instant) -> i64 {
    t.elapsed().as_nanos() as i64
}


fn main() {
    let n = 20000000i64;
    let t0 = Instant::now();
    let mut s = 0.0f64;
    for i in 0..n {
        let d = (2 * i + 1) as f64;
        if i % 2 == 0 { s += 1.0 / d; } else { s -= 1.0 / d; }
    }
    let pi = s * 4.0;
    let el = now_ns(&t0);
    println!("{:.6}", pi); println!("T"); println!("{}", el);
}
