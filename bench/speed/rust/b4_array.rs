use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let n: i64 = 2000000;
    let v: Vec<i64> = (0..n).map(|i| i * 3 + 1).collect();
    let mut s: i64 = 0;
    for i in 0..n { s += v[i as usize]; }
    let mut t: i64 = 0;
    for i in (0..n).step_by(7) { t += v[i as usize]; }
    let el = now_ns(&t0);
    println!("{}", s); println!("{}", t); println!("T"); println!("{}", el);
}
