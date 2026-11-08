use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let n: i64 = 500000;
    let mut acc: i64 = 0;
    for i in 0..n {
        let s = i.to_string();
        let len = s.len() as i64;
        let v: i64 = s.parse().unwrap();
        acc += len;
        acc += v;
    }
    let el = now_ns(&t0);
    println!("{}", acc); println!("T"); println!("{}", el);
}
