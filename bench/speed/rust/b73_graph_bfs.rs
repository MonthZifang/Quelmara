use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

fn main() {
    let t0 = Instant::now();
    let n: i64 = 1000;
    let mut adj = vec![0i64; (n * n) as usize];
    let mut seed: u64 = 55;
    for _e in 0..5000 {
        seed = (seed * 1103515245 + 12345) % 2147483648;
        let u = (seed % (n as u64)) as i64;
        seed = (seed * 1103515245 + 12345) % 2147483648;
        let v = (seed % (n as u64)) as i64;
        adj[(u * n + v) as usize] = 1;
    }
    let mut visited = vec![0i64; n as usize];
    let mut queue = vec![0i64; n as usize];
    let mut front = 0i64;
    let mut back = 0i64;
    queue[0] = 0;
    visited[0] = 1;
    back = 1;
    let mut cnt = 0i64;
    while front < back {
        let u = queue[front as usize];
        front += 1;
        cnt += 1;
        for v in 0..n {
            if adj[(u * n + v) as usize] != 0 && visited[v as usize] == 0 {
                visited[v as usize] = 1;
                queue[back as usize] = v;
                back += 1;
            }
        }
    }
    let el = now_ns(&t0);
    println!("{}", cnt); println!("T"); println!("{}", el);
}
