use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let n: i64 = 1000000;
    let mut a = vec![0i64; n as usize];
    for i in 0..n { a[i as usize] = i; }
    let mut acc = 0i64;
    for _j in 0..10 {
        for k in 0..n { acc += a[k as usize]; }
    }
    let el = now_ns(&t0);
    println!("{}", acc); println!("T"); println!("{}", el);
}
