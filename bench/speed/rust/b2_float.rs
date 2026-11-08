use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let n: i64 = 5000000;
    let mut acc = 0.0f64;
    for i in 1..=n { acc += 1.0 / (i as f64); }
    let el = now_ns(&t0);
    println!("{:.6}", acc); println!("T"); println!("{}", el);
}
