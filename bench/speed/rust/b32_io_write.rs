use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let n: i64 = 1000000;
    let mut buf = vec![0i64; n as usize];
    for i in 0..n { buf[i as usize] = i * 2 + 1; }
    let el = now_ns(&t0);
    println!("{}", buf[(n - 1) as usize]); println!("T"); println!("{}", el);
}
