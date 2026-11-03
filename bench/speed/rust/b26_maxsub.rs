// b26_maxsub —— DP：Kadane 最大子数组 2000 万
// 与 C / quelmara 版算法逐字等价，只打印"结果 + T + 纳秒耗时"。
use std::time::Instant;

fn now_ns(t: &Instant) -> i64 {
    t.elapsed().as_nanos() as i64
}


fn main() {
    let n = 20000000i64;
    let mut seed = 42u64;
    let t0 = Instant::now();
    let mut best = 0i64; let mut cur = 0i64;
    for _ in 0..n {
        seed = (seed.wrapping_mul(1103515245).wrapping_add(12345)) % 2147483648;
        let v = (seed % 201) as i64 - 100;
        cur += v;
        if cur < 0 { cur = 0; }
        if cur > best { best = cur; }
    }
    let el = now_ns(&t0);
    println!("{}", best); println!("T"); println!("{}", el);
}
