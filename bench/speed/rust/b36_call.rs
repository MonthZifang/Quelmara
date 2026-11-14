use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

// v4.115 fairness audit: black_box on the result stops LLVM from replacing
// the loop by a closed form (it does so even with an opaque bound).
// black_box emits zero instructions; algorithm and checksum are unchanged.
fn add3(a: i64, b: i64, c: i64) -> i64 { std::hint::black_box(a + b + c) }
fn main() {
    let t0 = Instant::now();
    let mut acc: i64 = 0;
    for i in 0..10000000 { acc = add3(acc, i, 1); }
    let el = now_ns(&t0);
    println!("{}", acc); println!("T"); println!("{}", el);
}
