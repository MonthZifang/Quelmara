use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let mut acc: i64 = 0;
    for n in 1..=5000000 {
        let mut s: i64 = 0;
        for k in 0..5 { s = s * n + k * 3 + 1; }
        acc += s % 1000003;
    }
    let el = now_ns(&t0);
    println!("{}", acc % 1000003); println!("T"); println!("{}", el);
}
