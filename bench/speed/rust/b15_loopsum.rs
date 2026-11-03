// b15_loopsum —— 最朴素循环累加 2 亿次（依赖链防折叠）
// 与 C / quelmara 版算法逐字等价，只打印"结果 + T + 纳秒耗时"。
use std::time::Instant;

fn now_ns(t: &Instant) -> i64 {
    t.elapsed().as_nanos() as i64
}


fn main() {
    let n = 200000000i64;
    let t0 = Instant::now();
    let mut s = 0i64; let mut x = 1i64;
    for i in 0..n {
        x = (x.wrapping_mul(31).wrapping_add(i)) | 1;
        s = s.wrapping_add(x & 1023);
    }
    let el = now_ns(&t0);
    println!("{}", s); println!("T"); println!("{}", el);
}
