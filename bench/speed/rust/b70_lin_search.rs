use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let n: i64 = 1000;
    let mut a = vec![0i64; n as usize];
    for i in 0..n { a[i as usize] = i * 3 + 7; }
    let mut found = 0i64;
    for j in 0..1000000 {
        let target = ((j * 37 + 11) % 3000) as i64;
        for k in 0..n {
            if a[k as usize] == target { found += 1; }
        }
    }
    let el = now_ns(&t0);
    println!("{}", found); println!("T"); println!("{}", el);
}
