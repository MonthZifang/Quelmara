use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn work(n: i64) -> i64 {
    let mut acc: i64 = 0;
    for i in 0..n { acc += (i * 7) % 13; }
    acc
}
fn main() {
    let t0 = Instant::now();
    let a = work(40000000);
    let b = work(40000000);
    let c = work(40000000);
    let d = work(40000000);
    let el = now_ns(&t0);
    println!("{}", a + b + c + d); println!("T"); println!("{}", el);
}
