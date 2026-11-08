use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let n: i64 = 5000000;
    let mut a = vec![0i64; n as usize];
    for i in 0..n { a[i as usize] = i * 2 + 1; }
    let el = now_ns(&t0);
    println!("{}", a[(n - 1) as usize]); println!("T"); println!("{}", el);
}
