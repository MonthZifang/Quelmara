use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let cap: i64 = 1048576;
    let mask = cap - 1;
    let n: i64 = 300000;
    let mut kt = vec![0i64; cap as usize];
    let mut vt = vec![0i64; cap as usize];
    for i in 1..=n {
        let k = i * 3 + 1;
        let mut h = (k * 2654435761i64) & mask;
        while kt[h as usize] != 0 { h = (h + 1) & mask; }
        kt[h as usize] = k;
        vt[h as usize] = k * 2;
    }
    let mut s: i64 = 0;
    for i in 1..=n {
        let k = i * 3 + 1;
        let mut h = (k * 2654435761i64) & mask;
        while kt[h as usize] != k { h = (h + 1) & mask; }
        s += vt[h as usize];
    }
    let el = now_ns(&t0);
    println!("{}", s); println!("T"); println!("{}", el);
}
