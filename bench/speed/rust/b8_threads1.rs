use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn work(n: i64) -> i64 {
    let mut acc: i64 = 0;
    for i in 0..n { acc += (i * 7) % 13; }
    acc
}
fn main() {
    let t0 = Instant::now();
    let r = work(160000000);
    let el = now_ns(&t0);
    println!("{}", r); println!("T"); println!("{}", el);
}
