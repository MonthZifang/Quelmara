use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let n: i64 = 1000000;
    let mut keys = vec![0i64; n as usize];
    let mut vals = vec![0i64; n as usize];
    for i in 0..n { keys[i as usize] = i; vals[i as usize] = i * 2; }
    for j in 0..n {
        let k = keys[j as usize];
        let v = vals[j as usize];
        keys[j as usize] = v;
        vals[j as usize] = k;
    }
    let el = now_ns(&t0);
    println!("{}", keys[0] + vals[0]); println!("T"); println!("{}", el);
}
