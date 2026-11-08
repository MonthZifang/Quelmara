use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn bsearch(a: &[i64], n: i64, target: i64) -> i64 {
    let mut lo = 0i64;
    let mut hi = n - 1;
    while lo <= hi {
        let mid = (lo + hi) / 2;
        if a[mid as usize] == target { return mid; }
        if a[mid as usize] < target { lo = mid + 1; } else { hi = mid - 1; }
    }
    -1
}
fn main() {
    let t0 = Instant::now();
    let n: i64 = 1000000;
    let mut a = vec![0i64; n as usize];
    for i in 0..n { a[i as usize] = i * 2; }
    let mut found = 0i64;
    for j in 0..1000000 {
        if bsearch(&a, n, j * 2) >= 0 { found += 1; }
    }
    let el = now_ns(&t0);
    println!("{}", found); println!("T"); println!("{}", el);
}
