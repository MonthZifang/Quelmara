use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn add3(a: i64, b: i64, c: i64) -> i64 { a + b + c }
fn main() {
    let t0 = Instant::now();
    let mut acc: i64 = 0;
    for i in 0..10000000 { acc = add3(acc, i, 1); }
    let el = now_ns(&t0);
    println!("{}", acc); println!("T"); println!("{}", el);
}
