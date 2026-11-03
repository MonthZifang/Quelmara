// b28_matrix —— 数值：矩阵乘法 300x300（朴素三重循环）
// 与 C / quelmara 版算法逐字等价，只打印"结果 + T + 纳秒耗时"。
use std::time::Instant;

fn now_ns(t: &Instant) -> i64 {
    t.elapsed().as_nanos() as i64
}


fn main() {
    let n = 300usize;
    let sz = n * n;
    let mut a = vec![0i64; sz];
    let mut b = vec![0i64; sz];
    let mut c = vec![0i64; sz];
    let mut seed = 7u64;
    for i in 0..sz {
        seed = (seed.wrapping_mul(1103515245).wrapping_add(12345)) % 2147483648;
        a[i] = (seed % 100) as i64;
        seed = (seed.wrapping_mul(1103515245).wrapping_add(12345)) % 2147483648;
        b[i] = (seed % 100) as i64;
    }
    let t0 = Instant::now();
    for r in 0..n {
        for k in 0..n {
            let av = a[r * n + k];
            let base = k * n;
            for j in 0..n { c[r * n + j] += av * b[base + j]; }
        }
    }
    let el = now_ns(&t0);
    let mut chk = 0i64;
    for i in 0..sz { chk = (chk + c[i]) % 1000000007; }
    println!("{}", chk); println!("T"); println!("{}", el);
}
