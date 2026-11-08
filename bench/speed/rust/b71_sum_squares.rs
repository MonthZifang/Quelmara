use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let mut acc = 0i64;
    for i in 1..=1000000 { acc += i * i; }
    let el = now_ns(&t0);
    println!("{}", acc % 1000003); println!("T"); println!("{}", el);
}
