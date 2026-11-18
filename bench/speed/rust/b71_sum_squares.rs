use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let mut acc = 0i64;
    // Match the C benchmark's per-iteration optimization barrier: otherwise
    // the compiler can replace the entire workload with a constant.
    for i in 1..=1000000 { acc = std::hint::black_box(acc + i * i); }
    let el = now_ns(&t0);
    println!("{}", acc % 1000003); println!("T"); println!("{}", el);
}
