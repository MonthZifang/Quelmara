use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let mut acc = 0i64;
    for i in 0..5000000 {
        if (i * 7 + 3) % 5 < 2 { acc += 1; } else { acc -= 1; }
    }
    let el = now_ns(&t0);
    println!("{}", acc); println!("T"); println!("{}", el);
}
