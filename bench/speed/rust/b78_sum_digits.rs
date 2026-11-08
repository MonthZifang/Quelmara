use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn digit_sum(mut n: i64) -> i64 {
    let mut s = 0i64;
    while n > 0 { s += n % 10; n /= 10; }
    s
}
fn main() {
    let t0 = Instant::now();
    let mut acc = 0i64;
    for i in 0..1000000 { acc += digit_sum(i); }
    let el = now_ns(&t0);
    println!("{}", acc); println!("T"); println!("{}", el);
}
