use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let n: i64 = 1000000;
    let mut lines = vec![0i64; n as usize];
    for i in 0..n { lines[i as usize] = i * 7 + 3; }
    let mut sum = 0i64;
    for j in 0..n { sum += lines[j as usize] % 100; }
    let el = now_ns(&t0);
    println!("{}", sum); println!("T"); println!("{}", el);
}
