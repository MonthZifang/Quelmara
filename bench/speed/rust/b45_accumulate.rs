use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let mut acc = 0i64;
    for n in 1..=1000000 {
        let mut s = 0i64;
        for k in 0..10 { s = s * n + k; }
        acc += s % 1000003;
    }
    let el = now_ns(&t0);
    println!("{}", acc); println!("T"); println!("{}", el);
}
