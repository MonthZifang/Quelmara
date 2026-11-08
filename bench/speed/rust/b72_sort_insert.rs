use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let n: i64 = 10000;
    let mut a = vec![0i64; n as usize];
    let mut seed: u64 = 777;
    for i in 0..n {
        seed = (seed * 1103515245 + 12345) % 2147483648;
        a[i as usize] = (seed % 100000) as i64;
    }
    for x in 1..n {
        let key = a[x as usize];
        let mut y = x - 1;
        while y >= 0 && a[y as usize] > key {
            a[(y + 1) as usize] = a[y as usize];
            y -= 1;
        }
        a[(y + 1) as usize] = key;
    }
    let el = now_ns(&t0);
    println!("{}", a[0]); println!("T"); println!("{}", el);
}
