use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let mut st = vec![0i64; 1000000];
    let mut top = 0i64;
    for i in 0..1000000 {
        st[top as usize] = i;
        top += 1;
        if i % 3 == 0 && top > 0 { st[(top - 1) as usize] += 1; }
    }
    let el = now_ns(&t0);
    println!("{}", st[(top - 1) as usize]); println!("T"); println!("{}", el);
}
