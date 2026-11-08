use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn murmur(mut h: i64, k: i64) -> i64 {
    let mut key = k;
    key = key.wrapping_mul(-862048943i64);
    key = (key << 13) | ((key >> 51) & 0x1FFFFFFFFFFF);
    key = key.wrapping_mul(-862048943i64);
    h ^= key;
    h = (h << 13) | ((h >> 51) & 0x1FFFFFFFFFFF);
    h.wrapping_mul(5) + 1
}
fn main() {
    let t0 = Instant::now();
    let mut acc = 0i64;
    for i in 0..1000000 { acc = murmur(acc, i); }
    let el = now_ns(&t0);
    println!("{}", acc); println!("T"); println!("{}", el);
}
