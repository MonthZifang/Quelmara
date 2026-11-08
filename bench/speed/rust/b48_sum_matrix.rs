use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let n: i64 = 500;
    let sz = n * n;
    let mut a = vec![0i64; sz as usize];
    for i in 0..sz { a[i as usize] = i; }
    let mut total = 0i64;
    for r in 0..n {
        let mut s = 0i64;
        for c in 0..n { s += a[(r * n + c) as usize]; }
        total += s;
    }
    let el = now_ns(&t0);
    println!("{}", total); println!("T"); println!("{}", el);
}
