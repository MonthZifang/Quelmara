use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn perm(arr: &mut [i64], k: i64, n: i64, acc: i64) -> i64 {
    if k == n {
        let mut h = 0i64;
        for i in 0..n { h = h * 31 + arr[i as usize]; }
        return acc + (h % 1000003);
    }
    let mut s = acc;
    for i in k..n {
        let t = arr[k as usize]; arr[k as usize] = arr[i as usize]; arr[i as usize] = t;
        s = perm(arr, k + 1, n, s);
        let t = arr[k as usize]; arr[k as usize] = arr[i as usize]; arr[i as usize] = t;
    }
    s
}
fn main() {
    let t0 = Instant::now();
    let mut a = [0i64; 10];
    for i in 0..10 { a[i] = i as i64 + 1; }
    let r = perm(&mut a, 0, 10, 0);
    let el = now_ns(&t0);
    println!("{}", r); println!("T"); println!("{}", el);
}
