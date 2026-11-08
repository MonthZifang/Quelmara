use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let mut x = 0i64;
    let mut y = 0i64;
    let mut seed: u64 = 12345;
    for _i in 0..2000000 {
        seed = (seed * 1103515245 + 12345) % 2147483648;
        let d = (seed % 4) as i64;
        if d == 0 { x += 1; } else if d == 1 { x -= 1; } else if d == 2 { y += 1; } else { y -= 1; }
    }
    let el = now_ns(&t0);
    println!("{}", x * 1000000 + y); println!("T"); println!("{}", el);
}
