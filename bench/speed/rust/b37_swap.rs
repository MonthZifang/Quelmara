use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let n: i64 = 10000;
    let mut a = vec![0i64; n as usize];
    let mut seed: u64 = 42;
    for i in 0..n {
        seed = (seed * 1103515245 + 12345) % 2147483648;
        a[i as usize] = (seed % 100000) as i64;
    }
    for _round in 0..100 {
        for j in 0..n - 1 {
            if a[j as usize] > a[j as usize + 1] {
                let t = a[j as usize];
                a[j as usize] = a[j as usize + 1];
                a[j as usize + 1] = t;
            }
        }
    }
    let el = now_ns(&t0);
    println!("{}", a[0]); println!("T"); println!("{}", el);
}
