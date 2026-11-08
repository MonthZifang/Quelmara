use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let cap: i64 = 262144;
    let mut buckets = vec![0i64; cap as usize];
    let mut cnt = 0i64;
    for j in 0..200000 {
        let h = (j * 2654435761i64) % cap;
        buckets[h as usize] += 1;
        cnt += 1;
    }
    let el = now_ns(&t0);
    println!("{}", cnt); println!("T"); println!("{}", el);
}
