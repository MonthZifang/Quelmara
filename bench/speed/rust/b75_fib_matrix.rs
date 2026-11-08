use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let mut a0 = 1i64;
    let mut a1 = 1i64;
    let mut a2 = 1i64;
    let mut a3 = 0i64;
    let mut n = 1000i64;
    while n > 0 {
        if n % 2 == 1 {
            let t = (a0 * a1 + a1 * a3) % 1000003;
            let u = (a0 * a2 + a1 * a3) % 1000003;
            let v = (a2 * a1 + a3 * a3) % 1000003;
            let w = (a2 * a1 + a3 * a3) % 1000003;
            a0 = t; a1 = u; a2 = v; a3 = w;
        }
        let b0 = (a0 * a0 + a1 * a2) % 1000003;
        let b1 = (a0 * a1 + a1 * a3) % 1000003;
        let b2 = (a2 * a0 + a3 * a2) % 1000003;
        let b3 = (a2 * a1 + a3 * a3) % 1000003;
        a0 = b0; a1 = b1; a2 = b2; a3 = b3;
        n /= 2;
    }
    let el = now_ns(&t0);
    println!("{}", a1); println!("T"); println!("{}", el);
}
