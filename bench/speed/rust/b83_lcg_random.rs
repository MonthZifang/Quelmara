use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let mut seed: u64 = 12345;
    let mut acc = 0i64;
    for _i in 0..10000000 {
        seed = (seed * 1103515245 + 12345) % 2147483648;
        acc += (seed % 100) as i64;
    }
    let el = now_ns(&t0);
    println!("{}", acc); println!("T"); println!("{}", el);
}
