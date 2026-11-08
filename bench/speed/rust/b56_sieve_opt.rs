use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let n: i64 = 2000000;
    let mut flags = vec![1i64; (n + 1) as usize];
    flags[0] = 0;
    flags[1] = 0;
    let mut p = 2;
    while p * p <= n {
        if flags[p as usize] != 0 {
            let mut q = p * p;
            while q <= n { flags[q as usize] = 0; q += p; }
        }
        p += 1;
    }
    let mut cnt = 0i64;
    for k in 2..=n { if flags[k as usize] != 0 { cnt += 1; } }
    let el = now_ns(&t0);
    println!("{}", cnt); println!("T"); println!("{}", el);
}
