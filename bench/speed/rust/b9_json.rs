use std::time::Instant;
fn now_ns(t: &Instant) -> i64 { t.elapsed().as_nanos() as i64 }

static DOC: &str = "{\"meta\":{\"version\":3,\"count\":30,\"flags\":[1,0,1]},\"items\":[{\"id\":1,\"name\":\"user_1\",\"score\":37,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":\"n1\"},{\"id\":2,\"name\":\"user_2\",\"score\":74,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":\"n2\"},{\"id\":3,\"name\":\"user_3\",\"score\":11,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":\"n3\"},{\"id\":4,\"name\":\"user_4\",\"score\":48,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":\"n4\"},{\"id\":5,\"name\":\"user_5\",\"score\":85,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":null},{\"id\":6,\"name\":\"user_6\",\"score\":22,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":\"n6\"},{\"id\":7,\"name\":\"user_7\",\"score\":59,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":\"n7\"},{\"id\":8,\"name\":\"user_8\",\"score\":96,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":\"n8\"},{\"id\":9,\"name\":\"user_9\",\"score\":33,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":\"n9\"},{\"id\":10,\"name\":\"user_10\",\"score\":70,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":null},{\"id\":11,\"name\":\"user_11\",\"score\":7,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":\"n11\"},{\"id\":12,\"name\":\"user_12\",\"score\":44,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":\"n12\"},{\"id\":13,\"name\":\"user_13\",\"score\":81,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":\"n13\"},{\"id\":14,\"name\":\"user_14\",\"score\":18,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":\"n14\"},{\"id\":15,\"name\":\"user_15\",\"score\":55,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":null},{\"id\":16,\"name\":\"user_16\",\"score\":92,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":\"n16\"},{\"id\":17,\"name\":\"user_17\",\"score\":29,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":\"n17\"},{\"id\":18,\"name\":\"user_18\",\"score\":66,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":\"n18\"},{\"id\":19,\"name\":\"user_19\",\"score\":3,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":\"n19\"},{\"id\":20,\"name\":\"user_20\",\"score\":40,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":null},{\"id\":21,\"name\":\"user_21\",\"score\":77,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":\"n21\"},{\"id\":22,\"name\":\"user_22\",\"score\":14,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":\"n22\"},{\"id\":23,\"name\":\"user_23\",\"score\":51,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":\"n23\"},{\"id\":24,\"name\":\"user_24\",\"score\":88,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":\"n24\"},{\"id\":25,\"name\":\"user_25\",\"score\":25,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":null},{\"id\":26,\"name\":\"user_26\",\"score\":62,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":\"n26\"},{\"id\":27,\"name\":\"user_27\",\"score\":99,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":\"n27\"},{\"id\":28,\"name\":\"user_28\",\"score\":36,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":\"n28\"},{\"id\":29,\"name\":\"user_29\",\"score\":73,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":\"n29\"},{\"id\":30,\"name\":\"user_30\",\"score\":10,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":null}]}";

fn jws(s: &[u8], p0: i64) -> i64 {
    let mut p = p0;
    let dn = s.len() as i64;
    while p < dn {
        let c = s[p as usize];
        if c == 32 || c == 9 || c == 10 || c == 13 { p += 1; } else { break; }
    }
    p
}
fn jstr(s: &[u8], p0: i64) -> i64 {
    let mut p = p0 + 1;
    let dn = s.len() as i64;
    while p < dn { if s[p as usize] == 34 { break; } p += 1; }
    p + 1
}
fn jnum(s: &[u8], p0: i64) -> (i64, i64) {
    let mut p = p0;
    let dn = s.len() as i64;
    let mut v = 0i64;
    let mut neg = false;
    if p < dn && s[p as usize] == 45 { neg = true; p += 1; }
    while p < dn {
        let c = s[p as usize];
        if c >= 48 && c <= 57 { v = v * 10 + (c - 48) as i64; p += 1; } else { break; }
    }
    if neg { v = -v; }
    (v, p)
}
fn jval(s: &[u8], p0: i64) -> (i64, i64) {
    let mut p = jws(s, p0);
    let dn = s.len() as i64;
    if p >= dn { return (0, p); }
    let c = s[p as usize];
    if c == 123 {
        let mut q = jws(s, p + 1);
        let mut acc = 0i64;
        if q < dn && s[q as usize] == 125 { return (0, q + 1); }
        loop {
            q = jws(s, q);
            q = jstr(s, q);
            q = jws(s, q);
            q = q + 1;
            let (val, st) = jval(s, q);
            acc += val;
            q = jws(s, st);
            if q < dn && s[q as usize] == 44 { q += 1; } else { break; }
        }
        (acc, q + 1)
    } else if c == 91 {
        let mut q = jws(s, p + 1);
        let mut acc = 0i64;
        if q < dn && s[q as usize] == 93 { return (0, q + 1); }
        loop {
            let (val, st) = jval(s, q);
            acc += val;
            q = jws(s, st);
            if q < dn && s[q as usize] == 44 { q += 1; } else { break; }
        }
        (acc, q + 1)
    } else if c == 34 {
        (0, jstr(s, p))
    } else if c == 45 || (c >= 48 && c <= 57) {
        jnum(s, p)
    } else {
        let mut q = p;
        while q < dn { let d = s[q as usize]; if d >= 97 && d <= 122 { q += 1; } else { break; } }
        (0, q)
    }
}
fn main() {
    let t0 = Instant::now();
    let bytes = DOC.as_bytes();
    let mut total = 0i64;
    for _ in 0..2000 {
        let (v, _) = jval(bytes, 0);
        total += v;
    }
    let el = now_ns(&t0);
    println!("{}", total); println!("T"); println!("{}", el);
}
