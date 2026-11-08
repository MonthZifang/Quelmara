use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let mut acc = 0i64;
    for _ in 0..100000 {
        let s = format!("{} {} {}", "hello", "world", "12345");
        acc += s.len() as i64;
    }
    let el = now_ns(&t0);
    println!("{}", acc); println!("T"); println!("{}", el);
}
