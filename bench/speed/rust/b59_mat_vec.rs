use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let n: i64 = 500;
    let sz = n * n;
    let mut mat = vec![0i64; sz as usize];
    let mut vec = vec![0i64; n as usize];
    for i in 0..sz { mat[i as usize] = (i * 7 + 3) % 100; }
    for j in 0..n { vec[j as usize] = (j * 13 + 1) % 100; }
    let mut total = 0i64;
    for r in 0..n {
        let mut s = 0i64;
        for c in 0..n { s += mat[(r * n + c) as usize] * vec[c as usize]; }
        total += s;
    }
    let el = now_ns(&t0);
    println!("{}", total); println!("T"); println!("{}", el);
}
