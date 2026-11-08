use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn pow_mod(mut base: i64, mut exp: i64, modu: i64) -> i64 {
    let mut result = 1i64;
    let mut b = base % modu;
    while exp > 0 {
        if exp % 2 == 1 { result = (result * b) % modu; }
        b = (b * b) % modu;
        exp /= 2;
    }
    result
}
fn main() {
    let t0 = Instant::now();
    let mut acc = 0i64;
    for i in 1..=1000000 { acc = (acc + pow_mod(i, i, 1000003)) % 1000003; }
    let el = now_ns(&t0);
    println!("{}", acc); println!("T"); println!("{}", el);
}
