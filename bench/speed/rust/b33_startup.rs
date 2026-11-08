use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn init() -> i64 {
    let mut s = 0i64;
    for i in 0..1000 { s += i; }
    s
}
fn main() {
    let t0 = Instant::now();
    let a = init();
    let b = init();
    let c = init();
    let d = init();
    let el = now_ns(&t0);
    println!("{}", a + b + c + d); println!("T"); println!("{}", el);
}
