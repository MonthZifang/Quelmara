use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let n: i64 = 256;
    let sz = n * n;
    let mut a = vec![0i64; sz as usize];
    for i in 0..sz { a[i as usize] = i % 2; }
    let mut b = vec![0i64; sz as usize];
    for r in 0..n {
        for c in 0..n {
            b[(r * n + c) as usize] = a[(c * n + (n - 1 - r)) as usize];
        }
    }
    let el = now_ns(&t0);
    println!("{}", b[0]); println!("T"); println!("{}", el);
}
