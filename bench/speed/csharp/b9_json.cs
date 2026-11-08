// b9_json - C# port (top-level statements, net6+).
// UNVERIFIED: no dotnet on the build box; algorithm mirrors c/b9_json.c.
using System;
using System.Diagnostics;
using System.Globalization;

string DOC = "{\"meta\":{\"version\":3,\"count\":30,\"flags\":[1,0,1]},\"items\":[{\"id\":1,\"name\":\"user_1\",\"score\":37,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":\"n1\"},{\"id\":2,\"name\":\"user_2\",\"score\":74,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":\"n2\"},{\"id\":3,\"name\":\"user_3\",\"score\":11,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":\"n3\"},{\"id\":4,\"name\":\"user_4\",\"score\":48,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":\"n4\"},{\"id\":5,\"name\":\"user_5\",\"score\":85,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":null},{\"id\":6,\"name\":\"user_6\",\"score\":22,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":\"n6\"},{\"id\":7,\"name\":\"user_7\",\"score\":59,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":\"n7\"},{\"id\":8,\"name\":\"user_8\",\"score\":96,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":\"n8\"},{\"id\":9,\"name\":\"user_9\",\"score\":33,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":\"n9\"},{\"id\":10,\"name\":\"user_10\",\"score\":70,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":null},{\"id\":11,\"name\":\"user_11\",\"score\":7,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":\"n11\"},{\"id\":12,\"name\":\"user_12\",\"score\":44,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":\"n12\"},{\"id\":13,\"name\":\"user_13\",\"score\":81,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":\"n13\"},{\"id\":14,\"name\":\"user_14\",\"score\":18,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":\"n14\"},{\"id\":15,\"name\":\"user_15\",\"score\":55,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":null},{\"id\":16,\"name\":\"user_16\",\"score\":92,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":\"n16\"},{\"id\":17,\"name\":\"user_17\",\"score\":29,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":\"n17\"},{\"id\":18,\"name\":\"user_18\",\"score\":66,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":\"n18\"},{\"id\":19,\"name\":\"user_19\",\"score\":3,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":\"n19\"},{\"id\":20,\"name\":\"user_20\",\"score\":40,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":null},{\"id\":21,\"name\":\"user_21\",\"score\":77,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":\"n21\"},{\"id\":22,\"name\":\"user_22\",\"score\":14,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":\"n22\"},{\"id\":23,\"name\":\"user_23\",\"score\":51,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":\"n23\"},{\"id\":24,\"name\":\"user_24\",\"score\":88,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":\"n24\"},{\"id\":25,\"name\":\"user_25\",\"score\":25,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":null},{\"id\":26,\"name\":\"user_26\",\"score\":62,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":\"n26\"},{\"id\":27,\"name\":\"user_27\",\"score\":99,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":\"n27\"},{\"id\":28,\"name\":\"user_28\",\"score\":36,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":\"n28\"},{\"id\":29,\"name\":\"user_29\",\"score\":73,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":true,\"note\":\"n29\"},{\"id\":30,\"name\":\"user_30\",\"score\":10,\"tags\":[\"a\",\"bb\",\"ccc\"],\"ok\":false,\"note\":null}]}";
long dn = DOC.Length;
long jws(string s, long p0) {
    long p = p0;
    while (p < dn) {
        char c = s[(int)p];
        if (c == ' ' || c == '\t' || c == '\n' || c == '\r') p++; else break;
    }
    return p;
}
long jstr(string s, long p0) {
    long p = p0 + 1;
    while (p < dn) { if (s[(int)p] == '"') break; p++; }
    return p + 1;
}
long jnum(string s, long p0, out long st) {
    long p = p0, v = 0; int neg = 0;
    if (p < dn && s[(int)p] == '-') { neg = 1; p++; }
    while (p < dn) {
        char c = s[(int)p];
        if (c >= '0' && c <= '9') { v = v * 10 + (c - '0'); p++; } else break;
    }
    if (neg != 0) v = -v;
    st = p; return v;
}
long jval(string s, long p0, out long st) {
    long p = jws(s, p0);
    if (p >= dn) { st = p; return 0; }
    char c = s[(int)p];
    if (c == '{') {
        long q = jws(s, p + 1); long acc = 0;
        if (q < dn && s[(int)q] == '}') { st = q + 1; return 0; }
        for (;;) {
            q = jws(s, q);
            q = jstr(s, q);
            q = jws(s, q);
            q++;
            acc += jval(s, q, out st);
            q = jws(s, st);
            if (q < dn && s[(int)q] == ',') q++; else break;
        }
        st = q + 1; return acc;
    }
    if (c == '[') {
        long q = jws(s, p + 1); long acc = 0;
        if (q < dn && s[(int)q] == ']') { st = q + 1; return 0; }
        for (;;) {
            acc += jval(s, q, out st);
            q = jws(s, st);
            if (q < dn && s[(int)q] == ',') q++; else break;
        }
        st = q + 1; return acc;
    }
    if (c == '"') { st = jstr(s, p); return 0; }
    if (c == '-' || (c >= '0' && c <= '9')) return jnum(s, p, out st);
    long q2 = p;
    while (q2 < dn) { char d = s[(int)q2]; if (d >= 'a' && d <= 'z') q2++; else break; }
    st = q2; return 0;
}

var sw = Stopwatch.StartNew();
long st = 0, total = 0;
for (long r = 0; r < 2000; r++) { st = 0; total += jval(DOC, 0, out st); }
long chk = total;

sw.Stop();
Console.WriteLine(chk);
Console.WriteLine("T");
Console.WriteLine(sw.ElapsedTicks * 1000000000L / Stopwatch.Frequency);
