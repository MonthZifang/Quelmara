use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let n: i64 = 20000000;
    let mut acc: i64 = 0;
    for i in 0..n { acc += (i * 7) % 13; }
    let el = now_ns(&t0);
    println!("{}", acc); println!("T"); println!("{}", el);
}
