use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let n: i64 = 1000;
    let sz = n * n;
    let mut a = vec![0i64; sz as usize];
    for i in 0..sz { a[i as usize] = (i * 7 + 3) % 100; }
    let mut sum = 0i64;
    for r in 0..n { sum += a[(r * n + r) as usize]; }
    let el = now_ns(&t0);
    println!("{}", sum); println!("T"); println!("{}", el);
}
