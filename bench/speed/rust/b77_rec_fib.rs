use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn fib(n: i64) -> i64 {
    if n <= 1 { n } else { fib(n - 1) + fib(n - 2) }
}
fn main() {
    let t0 = Instant::now();
    let r = fib(25);
    let el = now_ns(&t0);
    println!("{}", r); println!("T"); println!("{}", el);
}
