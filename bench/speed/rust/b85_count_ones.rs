use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn popcount(mut x: i64) -> i64 {
    let mut c = 0i64;
    while x != 0 { c += x & 1; x >>= 1; }
    c
}
fn main() {
    let t0 = Instant::now();
    let mut acc = 0i64;
    for i in 0..5000000 { acc += popcount(i); }
    let el = now_ns(&t0);
    println!("{}", acc); println!("T"); println!("{}", el);
}
