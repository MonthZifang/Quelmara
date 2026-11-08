#!/usr/bin/env python3
"""Verify a generated language's bench checksums against the canonical C ones.

Usage:
  python3 tools/benchgen/verify_lang.py <lang> [bench_ids...]
    <lang> in: go cpp python rust zig nim d ada fortran java csharp
  Compiles/runs each <lang>/<bench>.<ext>, compares the printed checksum
  (everything before the 'T' line) with /tmp/c_checksums.json.

Exit code 0 if ALL given benches match C (or are absent -> reported separately,
absent is NOT a failure here; the runner prints SKIP). Exit 1 if any present
bench mismatches C.
"""
import os, subprocess, sys, json, shutil, glob

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SPEED = os.path.join(ROOT, "bench", "speed")
CK = json.load(open("/tmp/c_checksums.json"))

EXT = {"go": ".go", "cpp": ".cpp", "python": ".py", "rust": ".rs", "zig": ".zig",
       "nim": ".nim", "d": ".d", "ada": ".adb", "fortran": ".f90", "java": ".java"}
BUILDERS = {}

def _cc_ldc(*names):
    def f():
        for n in names:
            p = shutil.which(n)
            if p: return p
        return None
    return f

def build(lang, b):
    ext = EXT[lang]
    src = os.path.join(SPEED, lang, b + ext)
    if not os.path.exists(src):
        return None, "absent"
    exe = f"/tmp/_v_{lang}_{b}"
    out = None
    if lang == "go":
        cc = shutil.which("go")
        r = subprocess.run([cc, "build", "-o", exe, src], capture_output=True, text=True,
                          cwd=os.path.join(SPEED, lang))
        if r.returncode != 0: return None, "compile:" + r.stderr.strip()[:200]
    elif lang == "cpp":
        cc = shutil.which("g++") or shutil.which("clang++")
        r = subprocess.run([cc, "-O2", "-I", os.path.join(SPEED, "c"), "-o", exe, src],
                          capture_output=True, text=True)
        if r.returncode != 0: return None, "compile:" + r.stderr.strip()[:200]
    elif lang == "python":
        return src, None  # run the source directly via interpreter
    elif lang == "rust":
        cc = shutil.which("rustc")
        r = subprocess.run([cc, "-O", "-o", exe, src], capture_output=True, text=True)
        if r.returncode != 0: return None, "compile:" + r.stderr.strip()[:200]
    elif lang == "zig":
        cc = shutil.which("zig")
        r = subprocess.run([cc, "build-exe", "-O", "ReleaseFast",
                            "-femit-bin=" + exe, src], capture_output=True, text=True)
        if r.returncode != 0: return None, "compile:" + r.stderr.strip()[:200]
    elif lang == "nim":
        cc = shutil.which("nim")
        r = subprocess.run([cc, "c", "-d:release", "--hints:off",
                           "--out:" + exe, src], capture_output=True, text=True)
        if r.returncode != 0: return None, "compile:" + r.stderr.strip()[:200]
    elif lang == "d":
        cc = shutil.which("ldc2")
        r = subprocess.run([cc, "-O3", "-of=" + exe, src], capture_output=True, text=True)
        if r.returncode != 0: return None, "compile:" + r.stderr.strip()[:200]
    elif lang == "ada":
        cc = shutil.which("gnatmake")
        r = subprocess.run([cc, "-O2", "-o", exe, src], capture_output=True, text=True)
        if r.returncode != 0: return None, "compile:" + r.stderr.strip()[:200]
    elif lang == "fortran":
        cc = shutil.which("gfortran")
        r = subprocess.run([cc, "-O2", "-o", exe, src], capture_output=True, text=True)
        if r.returncode != 0: return None, "compile:" + r.stderr.strip()[:200]
    elif lang == "java":
        # compile to a temp dir, then run the public class (no package)
        d = f"/tmp/_vjava_{b}"; os.makedirs(d, exist_ok=True)
        r = subprocess.run(["javac", "-d", d, src], capture_output=True, text=True)
        if r.returncode != 0: return None, "compile:" + r.stderr.strip()[:200]
        return d, None
    return exe, None

def run(lang, target):
    if lang == "python":
        r = subprocess.run([sys.executable, target], capture_output=True, text=True, timeout=120)
    elif lang == "java":
        r = subprocess.run(["java", "-cp", target, "Main"], capture_output=True, text=True, timeout=120)
    else:
        r = subprocess.run([target], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return "RUN_ERR:" + (r.stderr or r.stdout).strip()[:150]
    lines = [l.strip() for l in r.stdout.splitlines() if l.strip()]
    if "T" in lines:
        i = lines.index("T"); return "\n".join(lines[:i])
    return r.stdout.strip().splitlines()[0] if r.stdout.strip() else "NO_T"

def main():
    lang = sys.argv[1]
    only = sys.argv[2:]
    benches = only if only else [os.path.basename(p)[:-len(EXT[lang])]
                                for p in glob.glob(os.path.join(SPEED, lang, "*" + EXT[lang]))]
    mism, absent, ok = [], [], 0
    for b in sorted(benches):
        tgt, err = build(lang, b)
        if err == "absent":
            absent.append(b); continue
        if err:
            mism.append((b, "BUILD:" + err)); continue
        got = run(lang, tgt)
        want = CK.get(b)
        if got == want:
            ok += 1
        else:
            mism.append((b, f"got={got!r} want={want!r}"))
    print(f"[{lang}] match={ok} absent={len(absent)} mismatch={len(mism)}")
    for b, m in mism:
        print(f"  MISMATCH {b}: {m}")
    sys.exit(1 if mism else 0)

if __name__ == "__main__":
    main()
