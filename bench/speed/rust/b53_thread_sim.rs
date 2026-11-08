use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn work(start: i64, end: i64) -> i64 {
    let mut s = 0i64;
    for i in start..end { s += i * 2 + 1; }
    s
}
fn main() {
    let t0 = Instant::now();
    let n: i64 = 10000000;
    let a = work(0, n / 4);
    let b = work(n / 4, n / 2);
    let c = work(n / 2, 3 * n / 4);
    let d = work(3 * n / 4, n);
    let el = now_ns(&t0);
    println!("{}", a + b + c + d); println!("T"); println!("{}", el);
}
