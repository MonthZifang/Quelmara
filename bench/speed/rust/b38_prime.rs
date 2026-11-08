use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn is_prime(n: i64) -> i64 {
    if n < 2 { return 0; }
    if n == 2 { return 1; }
    if n % 2 == 0 { return 0; }
    let mut d = 3;
    while d * d <= n {
        if n % d == 0 { return 0; }
        d += 2;
    }
    1
}
fn main() {
    let t0 = Instant::now();
    let mut cnt = 0i64;
    for i in 0..100000 { if is_prime(i) == 1 { cnt += 1; } }
    let el = now_ns(&t0);
    println!("{}", cnt); println!("T"); println!("{}", el);
}
