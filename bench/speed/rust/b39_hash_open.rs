use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let cap: i64 = 1048576;
    let mut keys = vec![0i64; cap as usize];
    let mut vals = vec![0i64; cap as usize];
    for j in 0..500000 {
        let h = (j * 2654435761i64) % cap;
        keys[h as usize] = j;
        vals[h as usize] = j * 2;
    }
    let mut found = 0i64;
    for k in 0..500000 {
        let h = (k * 2654435761i64) % cap;
        if keys[h as usize] == k { found += 1; }
    }
    let el = now_ns(&t0);
    println!("{}", found); println!("T"); println!("{}", el);
}
