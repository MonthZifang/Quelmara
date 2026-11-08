use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn bitrev(x: i64) -> i64 {
    let mut v = x;
    let mut r = 0i64;
    for _i in 0..32 {
        r = (r << 1) | (v & 1);
        v >>= 1;
    }
    r
}
fn main() {
    let t0 = Instant::now();
    let mut acc = 0i64;
    for j in 0..1000000 { acc ^= bitrev(j); }
    let el = now_ns(&t0);
    println!("{}", acc); println!("T"); println!("{}", el);
}
