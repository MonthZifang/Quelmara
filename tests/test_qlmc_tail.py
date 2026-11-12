#!/usr/bin/env python3
"""Standalone qlmc self-tail regression (correctness/IR only, not a benchmark).

Example:
  python3 tests/test_qlmc_tail.py --compiler build/qlmc.exe --reference old.exe

Stage-0 cross-checks s_tail_self only: its bare-return semantics are incompatible
with qlmc, so it must NOT compile or validate s_tail_ret0. The optional reference
is another qlmc and checks both small fixtures. Only the candidate runs the
million-deep fixture: a recursive reference need not survive that stack depth.
All products live in a fresh private temporary directory; no benchmark or core
source is modified and stale build products can never satisfy these checks.
"""

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SELF_OUTPUT = (
    "2211\n1122\n23451\n6\n0\n1\n2\n17\n907\n3\n0\n5050\n-2\ntail-self-ok\n"
)
RET0_OUTPUT = "tail-ret0-ok\n"
DEEP_OUTPUT = "tail-deep-ok\n"
DEEP_SOURCE = """// Independent correctness fixture: no benchmark timing or source rewriting.
fn rec_sum(n: int) -> int {
    if n <= 0 { return 0 }
    return n + rec_sum(n - 1)
}
fn tail_direct(n: int) -> int {
    if n <= 0 { return 71 }
    return tail_direct(n - 1)
}
fn main() {
    assert(rec_sum(1000000) == 500000500000, "million-deep additive self tail")
    assert(tail_direct(1000000) == 71, "million-deep direct self tail")
    print("tail-deep-ok")
}
"""


class Failure(RuntimeError):
    pass


def run(command, env, timeout, label):
    try:
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True,
                                timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise Failure(f"{label}: timeout after {timeout}s\n"
                      f"stdout: {exc.stdout!r}\nstderr: {exc.stderr!r}") from exc
    if result.returncode:
        raise Failure(f"{label}: exit {result.returncode}\n"
                      f"stdout: {result.stdout.decode(errors='replace')}\n"
                      f"stderr: {result.stderr.decode(errors='replace')}")
    return result.stdout.replace(b"\r\n", b"\n")


def compile_run(driver, source, output, env, args, label, stage0=False):
    if output.exists():
        raise Failure(f"{label}: refusing non-fresh output {output}")
    command = driver + ["build", str(source), "-o", str(output)]
    command += ["--target", "win"] if stage0 else ["-j1"]
    run(command, env, args.build_timeout, label + " build")
    if not output.is_file() or output.stat().st_size == 0:
        raise Failure(f"{label}: compiler did not create a fresh executable")
    return run(args.runner + [str(output)], env, args.run_timeout, label + " run")


def expect(output, expected, label):
    if output != expected.encode():
        raise Failure(f"{label}: stdout mismatch\nexpected: {expected!r}\n"
                      f"actual: {output!r}")
    print(f"PASS: {label}", flush=True)


def check_ir(dump):
    text = dump.decode("utf-8", errors="replace")
    headers = re.findall(r"^=== fn (\S+)\s+.*===\s*$", text, re.M)
    if headers != ["rec_sum"]:
        raise Failure(f"irdump: expected only rec_sum, got {headers!r}\n{text}")
    rows = re.findall(r"^\s*(\d+)\s+(\w+)\s+dst=.*?\s+imm=(-?\d+)(?:\([^\n]*\))?\s*$",
                      text, re.M)
    if not rows:
        raise Failure(f"irdump: no instructions parsed\n{text}")
    # rec_sum has no callees other than itself; rejecting every CALL here is
    # stronger than matching an unstable function-table index in its imm.
    if any(op == "CALL" for _, op, _ in rows):
        raise Failure(f"irdump: self CALL remains in rec_sum\n{text}")
    labels = {int(imm): int(index) for index, op, imm in rows if op == "LAB"}
    backedges = [(int(index), labels[int(imm)])
                 for index, op, imm in rows
                 if op in ("JMP", "JZ", "JNZ", "JCMP", "JCMPI")
                 and int(imm) in labels and labels[int(imm)] < int(index)]
    if not backedges:
        raise Failure(f"irdump: rec_sum has no branch to an earlier label\n{text}")
    print(f"PASS: b58 rec_sum IR: no self CALL; backedges {backedges}", flush=True)


def positive_seconds(value):
    number = float(value)
    if not 0 < number < float("inf"):
        raise argparse.ArgumentTypeError("timeout must be finite and positive")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", type=Path, default=ROOT / "build/qlmc.exe")
    parser.add_argument("--reference", type=Path, help="optional pre-optimization qlmc")
    parser.add_argument("--build-timeout", type=positive_seconds, default=180)
    parser.add_argument("--run-timeout", type=positive_seconds, default=60)
    args = parser.parse_args(argv)
    for name in ("compiler", "reference"):
        value = getattr(args, name)
        if value is not None:
            value = value.resolve()
            if not value.is_file():
                parser.error(f"{name} does not exist: {value}")
            setattr(args, name, value)
    wine = shutil.which("wine") if os.name != "nt" else None
    if os.name != "nt" and not wine:
        parser.error("Wine is required to run Windows compiler/products")
    args.runner = [wine] if wine else []
    env = os.environ.copy()
    env["DISPLAY"] = ":1"
    env.setdefault("WINEDEBUG", "-all")
    env.setdefault("WINEDLLOVERRIDES", "winemenubuilder.exe=d")
    candidate = args.runner + [str(args.compiler)]
    try:
        with tempfile.TemporaryDirectory(prefix="qlmc-tail-") as directory:
            work = Path(directory)
            print(f"fresh work directory: {work}", flush=True)
            outputs = {}
            for name, expected in (("s_tail_self", SELF_OUTPUT), ("s_tail_ret0", RET0_OUTPUT)):
                source = ROOT / "tests" / (name + ".qma")
                output = compile_run(candidate, source, work / (name + "_candidate.exe"),
                                     env, args, "candidate " + name)
                expect(output, expected, "candidate " + name + " assertions/output")
                outputs[name] = output
                if args.reference:
                    reference = compile_run(args.runner + [str(args.reference)], source,
                                            work / (name + "_reference.exe"), env, args,
                                            "reference " + name)
                    expect(reference, expected, "reference " + name + " assertions/output")
                    if reference != output:
                        raise Failure(f"{name}: candidate/reference stdout differ")
                    print(f"PASS: candidate/reference {name} agree", flush=True)
            stage0 = compile_run([sys.executable, str(ROOT / "tools/stage0/qlm_cli.py")],
                                 ROOT / "tests/s_tail_self.qma", work / "s_tail_self_stage0.exe",
                                 env, args, "stage0 s_tail_self", stage0=True)
            expect(stage0, SELF_OUTPUT, "stage0 s_tail_self assertions/output")
            if stage0 != outputs["s_tail_self"]:
                raise Failure("s_tail_self: candidate/stage0 stdout differ")
            print("SKIP: stage0 RET0 (known incompatible bare-return semantics)", flush=True)
            deep = work / "tail_deep.qma"
            deep.write_text(DEEP_SOURCE, encoding="utf-8")
            output = compile_run(candidate, deep, work / "tail_deep.exe", env, args,
                                 "candidate million-deep")
            expect(output, DEEP_OUTPUT, "candidate million-deep assertions/output")
            dump = run(candidate + ["irdump", str(ROOT / "bench/speed/quelmara/b58_rec_sum.qma"),
                                    "rec_sum"], env, args.build_timeout, "b58 rec_sum irdump")
            check_ir(dump)
    except (Failure, OSError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("PASS: all tail regression checks (no performance requirement)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
