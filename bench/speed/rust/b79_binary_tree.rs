use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let mut keys = vec![0i64; 50000];
    let mut n = 0i64;
    let mut seed: u64 = 42;
    for _i in 0..50000 {
        seed = (seed * 1103515245 + 12345) % 2147483648;
        let key = (seed % 100000) as i64;
        let mut pos = n;
        for j in 0..n {
            if keys[j as usize] > key { pos = j; break; }
        }
        for k in (pos + 1..=n).rev() { keys[k as usize] = keys[(k - 1) as usize]; }
        keys[pos as usize] = key;
        n += 1;
    }
    let el = now_ns(&t0);
    println!("{}", keys[0]); println!("T"); println!("{}", el);
}
