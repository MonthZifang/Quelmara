use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let n: i64 = 100;
    let sz = n * n;
    let mut dist = vec![999999i64; sz as usize];
    for k in 0..n { dist[(k * n + k) as usize] = 0; }
    let mut seed: u64 = 7;
    for _e in 0..300 {
        seed = (seed * 1103515245 + 12345) % 2147483648;
        let u = (seed % (n as u64)) as i64;
        seed = (seed * 1103515245 + 12345) % 2147483648;
        let v = (seed % (n as u64)) as i64;
        seed = (seed * 1103515245 + 12345) % 2147483648;
        let w = (seed % 100 + 1) as i64;
        dist[(u * n + v) as usize] = w;
    }
    for a in 0..n {
        for b in 0..n {
            for c in 0..n {
                let d1 = dist[(b * n + c) as usize];
                let d2 = dist[(b * n + a) as usize] + dist[(a * n + c) as usize];
                if d2 < d1 { dist[(b * n + c) as usize] = d2; }
            }
        }
    }
    let el = now_ns(&t0);
    println!("{}", dist[1]); println!("T"); println!("{}", el);
}
