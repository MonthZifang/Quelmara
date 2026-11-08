use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let mut acc: i64 = 0;
    for i in 0..20000000 {
        acc += ((i ^ (i << 3)) & 0xFFFF) + ((i >> 2) | (i << 5));
    }
    let el = now_ns(&t0);
    println!("{}", acc); println!("T"); println!("{}", el);
}
