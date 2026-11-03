// b22_knapsack —— DP：0/1 背包 800 x 800
// 与 C / quelmara 版算法逐字等价，只打印"结果 + T + 纳秒耗时"。
use std::time::Instant;

fn now_ns(t: &Instant) -> i64 {
    t.elapsed().as_nanos() as i64
}


fn main() {
    let n = 800usize; let cap = 800usize;
    let mut wt = vec![0i64; n];
    let mut vl = vec![0i64; n];
    let mut seed = 999u64;
    for i in 0..n {
        seed = (seed.wrapping_mul(1103515245).wrapping_add(12345)) % 2147483648;
        wt[i] = (seed % 50) as i64 + 1;
        seed = (seed.wrapping_mul(1103515245).wrapping_add(12345)) % 2147483648;
        vl[i] = (seed % 100) as i64 + 1;
    }
    let t0 = Instant::now();
    let mut dp = vec![0i64; cap + 1];
    for it in 0..n {
        let w = wt[it] as usize;
        let mut c = cap;
        while c >= w {
            let cand = dp[c - w] + vl[it];
            if cand > dp[c] { dp[c] = cand; }
            c -= 1;
        }
    }
    let el = now_ns(&t0);
    println!("{}", dp[cap]); println!("T"); println!("{}", el);
}
