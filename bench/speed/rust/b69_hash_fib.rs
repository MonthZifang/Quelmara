use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn fib_hash(key: i64, cap: i64) -> i64 {
    (((key * 2654435761i64) % cap + cap) % cap)
}
fn main() {
    let t0 = Instant::now();
    let cap: i64 = 524288;
    let mut tab = vec![0i64; cap as usize];
    let mut cnt = 0i64;
    for j in 0..500000 {
        let h = fib_hash(j, cap);
        tab[h as usize] += 1;
        cnt += 1;
    }
    let el = now_ns(&t0);
    println!("{}", cnt); println!("T"); println!("{}", el);
}
