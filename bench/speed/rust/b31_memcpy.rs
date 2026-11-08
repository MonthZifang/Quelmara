use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let n: i64 = 12500000;
    let mut src = vec![0i64; n as usize];
    let mut dst = vec![0i64; n as usize];
    for i in 0..n { src[i as usize] = i; }
    for j in 0..n { dst[j as usize] = src[j as usize]; }
    let el = now_ns(&t0);
    println!("{}", dst[(n - 1) as usize]); println!("T"); println!("{}", el);
}
