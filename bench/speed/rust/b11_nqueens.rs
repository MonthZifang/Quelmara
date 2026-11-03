// b11_nqueens —— 回溯：8 皇后 x 2000 轮
// 与 C / quelmara 版算法逐字等价，只打印"结果 + T + 纳秒耗时"。
use std::time::Instant;

fn now_ns(t: &Instant) -> i64 {
    t.elapsed().as_nanos() as i64
}


fn solve(col: &mut Vec<i64>, n: i64, r: i64) -> i64 {
    if r == n { return 1; }
    let mut cnt = 0i64;
    for c in 0..n {
        let mut ok = true;
        for k in 0..r {
            let cc = col[k as usize];
            if cc == c { ok = false; }
            let d = cc - c;
            if d == k - r || d == r - k { ok = false; }
        }
        if ok { col[r as usize] = c; cnt += solve(col, n, r + 1); }
    }
    cnt
}
fn main() {
    let n = 8i64;
    let mut col = vec![0i64; n as usize];
    let t0 = Instant::now();
    let mut total = 0i64;
    for _ in 0..2000 { total += solve(&mut col, n, 0); }
    let el = now_ns(&t0);
    println!("{}", total); println!("T"); println!("{}", el);
}
