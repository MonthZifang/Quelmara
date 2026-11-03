// b18_insertion —— 排序：插入排序 8 万
// 与 C / quelmara 版算法逐字等价，只打印"结果 + T + 纳秒耗时"。
use std::time::Instant;

fn now_ns(t: &Instant) -> i64 {
    t.elapsed().as_nanos() as i64
}


fn main() {
    let n = 80000usize;
    let mut a = vec![0i64; n];
    let mut seed = 12345u64;
    for i in 0..n {
        seed = (seed.wrapping_mul(1103515245).wrapping_add(12345)) % 2147483648;
        a[i] = (seed % 100000) as i64;
    }
    let t0 = Instant::now();
    for x in 1..n {
        let key = a[x];
        let mut y = x as i64 - 1;
        while y >= 0 && a[y as usize] > key {
            a[(y + 1) as usize] = a[y as usize];
            y -= 1;
        }
        a[(y + 1) as usize] = key;
    }
    let el = now_ns(&t0);
    let mut chk = 0i64;
    for i in 0..n { chk = (chk + a[i] * ((i + 1) as i64)) % 1000000007; }
    println!("{}", chk); println!("T"); println!("{}", el);
}
