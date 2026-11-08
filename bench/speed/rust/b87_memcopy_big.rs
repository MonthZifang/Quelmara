use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let n: i64 = 12500000;
    let mut src = vec![0i64; n as usize];
    let mut dst = vec![0i64; n as usize];
    for i in 0..n { src[i as usize] = i * 7 + 1; }
    dst.copy_from_slice(&src);
    let el = now_ns(&t0);
    let chk = dst[0] + dst[6250000] + dst[(n - 1) as usize];
    println!("{}", chk); println!("T"); println!("{}", el);
}
