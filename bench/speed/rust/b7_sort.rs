use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn qsort(a: &mut [i64], lo: i64, hi: i64) {
    if lo >= hi { return; }
    let p = a[hi as usize];
    let mut i = lo;
    for j in lo..hi {
        if a[j as usize] < p {
            let t = a[i as usize]; a[i as usize] = a[j as usize]; a[j as usize] = t;
            i += 1;
        }
    }
    let t = a[i as usize]; a[i as usize] = a[hi as usize]; a[hi as usize] = t;
    qsort(a, lo, i - 1);
    qsort(a, i + 1, hi);
}
fn main() {
    let t0 = Instant::now();
    let n: i64 = 200000;
    let mut v: Vec<i64> = Vec::with_capacity(n as usize);
    let mut x: i64 = 12345;
    for _ in 0..n { x = (x * 1103515245 + 12345) & 2147483647; v.push(x); }
    qsort(&mut v, 0, n - 1);
    let mut s: i64 = 0;
    for i in 0..n { s += v[i as usize] % 1000; }
    let el = now_ns(&t0);
    println!("{}", v[0]); println!("{}", v[(n - 1) as usize]); println!("{}", s);
    println!("T"); println!("{}", el);
}
