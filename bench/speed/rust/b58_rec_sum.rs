use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

// v4.115 fairness audit: per-level black_box stops compile-time evaluation /
// closed-form replacement of the recursion (zero instructions).
fn rec_sum(n: i64) -> i64 {
    if n <= 0 { 0 } else { std::hint::black_box(n + rec_sum(n - 1)) }
}
fn main() {
    let t0 = Instant::now();
    let mut acc = 0i64;
    for i in 1..=100 { acc += rec_sum(10000); }
    let el = now_ns(&t0);
    println!("{}", acc); println!("T"); println!("{}", el);
}
