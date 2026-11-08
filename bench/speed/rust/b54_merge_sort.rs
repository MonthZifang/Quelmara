use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn merge(a: &mut [i64], lo: i64, mid: i64, hi: i64, tmp: &mut [i64]) {
    let mut i = lo;
    let mut j = mid;
    let mut k = 0i64;
    while i < mid && j < hi {
        if a[i as usize] <= a[j as usize] {
            tmp[k as usize] = a[i as usize]; i += 1;
        } else {
            tmp[k as usize] = a[j as usize]; j += 1;
        }
        k += 1;
    }
    while i < mid { tmp[k as usize] = a[i as usize]; i += 1; k += 1; }
    while j < hi { tmp[k as usize] = a[j as usize]; j += 1; k += 1; }
    for x in 0..k { a[(lo + x) as usize] = tmp[x as usize]; }
}
fn msort(a: &mut [i64], lo: i64, hi: i64, tmp: &mut [i64]) {
    if hi - lo <= 1 { return; }
    let mid = (lo + hi) / 2;
    msort(a, lo, mid, tmp);
    msort(a, mid, hi, tmp);
    merge(a, lo, mid, hi, tmp);
}
fn main() {
    let t0 = Instant::now();
    let n: i64 = 100000;
    let mut a = vec![0i64; n as usize];
    let mut tmp = vec![0i64; n as usize];
    let mut seed: u64 = 12345;
    for i in 0..n {
        seed = (seed * 1103515245 + 12345) % 2147483648;
        a[i as usize] = (seed % 1000000) as i64;
    }
    msort(&mut a, 0, n, &mut tmp);
    let el = now_ns(&t0);
    println!("{}", a[0]); println!("T"); println!("{}", el);
}
