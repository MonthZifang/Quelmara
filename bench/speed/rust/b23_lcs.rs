// b23_lcs —— DP：最长公共子序列 1500x1500（滚动数组）
// 与 C / quelmara 版算法逐字等价，只打印"结果 + T + 纳秒耗时"。
use std::time::Instant;

fn now_ns(t: &Instant) -> i64 {
    t.elapsed().as_nanos() as i64
}


fn main() {
    let n = 1500usize;
    let mut prev = vec![0i64; n + 1];
    let mut cur = vec![0i64; n + 1];
    let t0 = Instant::now();
    for r in 1..=n {
        for c in 1..=n {
            let av = ((r as i64) * 7 + 3) % 4;
            let bv = ((c as i64) * 11 + 5) % 4;
            if av == bv {
                cur[c] = prev[c - 1] + 1;
            } else {
                cur[c] = if prev[c] > cur[c - 1] { prev[c] } else { cur[c - 1] };
            }
        }
        for c in 0..=n { prev[c] = cur[c]; }
    }
    let el = now_ns(&t0);
    println!("{}", prev[n]); println!("T"); println!("{}", el);
}
