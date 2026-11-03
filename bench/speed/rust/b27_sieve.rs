// b27_sieve —— 筛法：埃氏筛 1000 万
// 与 C / quelmara 版算法逐字等价，只打印"结果 + T + 纳秒耗时"。
use std::time::Instant;

fn now_ns(t: &Instant) -> i64 {
    t.elapsed().as_nanos() as i64
}


fn main() {
    let n = 10000000usize;
    let t0 = Instant::now();
    let mut c = vec![1u8; n + 1];
    c[0] = 0; c[1] = 0;
    let mut p = 2usize;
    while p * p <= n {
        if c[p] == 1 {
            let mut q = p * p;
            while q <= n { c[q] = 0; q += p; }
        }
        p += 1;
    }
    let mut cnt = 0i64;
    for i in 0..=n { cnt += c[i] as i64; }
    let el = now_ns(&t0);
    println!("{}", cnt); println!("T"); println!("{}", el);
}
