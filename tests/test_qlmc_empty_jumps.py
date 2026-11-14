#!/usr/bin/env python3
"""Execute the real qlmc empty-jump helper in a small, extracted QMA fixture.

No Python model of the optimization, full bootstrap, or benchmark is involved.
Both stage0 and the seed compile/run the same freshly generated source.
Example: python3 tests/test_qlmc_empty_jumps.py --seed build/perf_session_4113/tailret2.exe
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
EXPECTED = b"empty-jumps-helper-ok\n"


def extract_block(source, kind, name):
    """Extract a real declaration, balancing braces outside strings/comments."""
    match = re.search(r"^" + kind + r"\s+" + re.escape(name) + r"\b", source, re.M)
    if not match:
        raise ValueError(f"missing {kind} {name}")
    start = source.index("{", match.start())
    depth = 0
    quoted = comment = escaped = False
    for index in range(start, len(source)):
        char = source[index]
        if comment:
            if char == "\n":
                comment = False
            continue
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if source[index:index + 2] == "//":
            comment = True
        elif char == '"':
            quoted = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[match.start():index + 1]
    raise ValueError(f"unclosed {kind} {name}")


DRIVER = r'''
fn emit(ir: vec[Ir], op: int, imm: int) {
    // Nonzero payloads detect accidental edits to retained instructions.
    ir.push(Ir { op: op, dst: 11, a: 22, b: 33, imm: imm })
}
fn same(left: Ir, right: Ir) -> bool {
    return left.op == right.op && left.dst == right.dst && left.a == right.a && left.b == right.b && left.imm == right.imm
}
fn check(ir: vec[Ir], removed: int) {
    let before = vec[Ir].new(len(ir))
    let mut i = 0
    while i < len(ir) { before.push(ir.get(i)) i = i + 1 }
    _opt_empty_jumps(ir)
    assert(len(ir) == len(before), "IR length unchanged")
    i = 0
    while i < len(ir) {
        if i == removed {
            let ins = ir.get(i)
            assert(ins.op == OP_NOP, "empty JMP removed")
            assert(ins.dst == 0 && ins.a == 0 && ins.b == 0 && ins.imm == 0, "removed JMP canonical NOP")
        } else {
            assert(same(ir.get(i), before.get(i)), "retained instruction unchanged")
        }
        i = i + 1
    }
    let once = vec[Ir].new(len(ir))
    i = 0
    while i < len(ir) { once.push(ir.get(i)) i = i + 1 }
    _opt_empty_jumps(ir)
    assert(len(ir) == len(once), "second pass length unchanged")
    i = 0
    while i < len(ir) {
        assert(same(ir.get(i), once.get(i)), "empty jump optimization idempotent")
        i = i + 1
    }
}
fn barrier(op: int) {
    let ir = vec[Ir].new(8)
    emit(ir, OP_JMP, 901)
    emit(ir, OP_NOP, 7)
    emit(ir, OP_LAB, 900)
    emit(ir, op, 17)
    emit(ir, OP_NOP, 8)
    emit(ir, OP_LAB, 901)
    check(ir, -1)
}
fn conditional(op: int) {
    let ir = vec[Ir].new(4)
    emit(ir, op, 901)
    emit(ir, OP_NOP, 7)
    emit(ir, OP_LAB, 901)
    check(ir, -1)
}
fn main() {
    let empty = vec[Ir].new(1)
    check(empty, -1)
    let direct = vec[Ir].new(4)
    emit(direct, OP_JMP, 901)
    emit(direct, OP_NOP, 7)
    emit(direct, OP_LAB, 901)
    check(direct, 0)
    let multiple = vec[Ir].new(12)
    emit(multiple, OP_JMP, 901)
    emit(multiple, OP_LAB, 800)
    emit(multiple, OP_NOP, 7)
    emit(multiple, OP_LAB, 900)
    emit(multiple, OP_NOP, 8)
    emit(multiple, OP_LAB, 901)
    emit(multiple, OP_NOP, 9)
    emit(multiple, OP_LAB, 902)
    // An operation AFTER the target must not prevent removal.
    emit(multiple, OP_CONST, 17)
    check(multiple, 0)
    barrier(OP_CONST)
    barrier(OP_LOAD)
    barrier(OP_CALL)
    barrier(OP_STORE)
    barrier(OP_STORE8)
    barrier(OP_STORED)
    barrier(OP_STOREX)
    barrier(OP_STORE8D)
    barrier(OP_STORE8X)
    barrier(OP_STORE8I)
    let backedge = vec[Ir].new(4)
    emit(backedge, OP_LAB, 901)
    emit(backedge, OP_NOP, 7)
    emit(backedge, OP_JMP, 901)
    emit(backedge, OP_NOP, 8)
    check(backedge, -1)
    conditional(OP_JZ)
    conditional(OP_JNZ)
    conditional(OP_JCMP)
    conditional(OP_JCMPI)
    conditional(OP_JCMPVLEN)
    conditional(OP_JCMPSTR)
    let missing = vec[Ir].new(5)
    emit(missing, OP_JMP, 901)
    emit(missing, OP_LAB, 900)
    emit(missing, OP_NOP, 7)
    emit(missing, OP_LAB, 902)
    check(missing, -1)
    let terminal = vec[Ir].new(1)
    emit(terminal, OP_JMP, 901)
    check(terminal, -1)
    print("empty-jumps-helper-ok")
}
'''


def generate(source):
    helper = extract_block(source, "fn", "_opt_empty_jumps")
    ir = extract_block(source, "struct", "Ir")
    constants = dict(re.findall(r"^const\s+(\w+)\s*=\s*([^\n]+)", source, re.M))
    text = helper + ir + DRIVER
    needed = set()
    while True:
        names = set(re.findall(r"\b[A-Z][A-Z0-9_]*\b", text))
        missing = {name for name in names if name.startswith("OP_") and name not in constants}
        if missing:
            raise ValueError(f"missing opcode constants: {sorted(missing)}")
        new = (names & constants.keys()) - needed
        if not new:
            break
        needed |= new
        text += "\n" + "\n".join(constants[name].split("//")[0] for name in new)
    consts = "\n".join(f"const {name} = {value}" for name, value in constants.items()
                       if name in needed)
    return f"module empty_jumps_helpers\n{consts}\n{ir}\n{helper}\n{DRIVER}"


def run(command, env, timeout, label):
    try:
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True,
                                timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{label}: timeout after {timeout}s; "
                           f"stdout={exc.stdout!r}; stderr={exc.stderr!r}") from exc
    if result.returncode:
        raise RuntimeError(f"{label}: exit {result.returncode}\n"
                           f"stdout: {result.stdout.decode(errors='replace')}\n"
                           f"stderr: {result.stderr.decode(errors='replace')}")
    return result.stdout.replace(b"\r\n", b"\n")


def positive_seconds(value):
    number = float(value)
    if not 0 < number < float("inf"):
        raise argparse.ArgumentTypeError("timeout must be finite and positive")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", "--baseline", dest="seed", type=Path,
                        default=ROOT / "build/perf_session_4113/tailret2.exe")
    parser.add_argument("--build-timeout", type=positive_seconds, default=180)
    parser.add_argument("--run-timeout", type=positive_seconds, default=30)
    args = parser.parse_args(argv)
    args.seed = args.seed.resolve()
    if not args.seed.is_file():
        parser.error(f"seed does not exist: {args.seed}")
    wine = shutil.which("wine") if os.name != "nt" else None
    if os.name != "nt" and not wine:
        parser.error("Wine is required to run Windows compiler/products")
    runner = [wine] if wine else []
    env = os.environ.copy()
    env.setdefault("WINEDEBUG", "-all")
    env.setdefault("WINEDLLOVERRIDES", "winemenubuilder.exe=d")
    try:
        fixture = generate((ROOT / "bootstrap/qlmc/qlmc.qma").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="qlmc-empty-jumps-") as directory:
            work = Path(directory)
            source = work / "helpers.qma"
            source.write_text(fixture, encoding="utf-8")
            print(f"fresh extracted fixture: {source}", flush=True)
            outputs = []
            for name in ("seed", "stage0"):
                exe = work / (name + ".exe")
                driver = (runner + [str(args.seed)] if name == "seed" else
                          [sys.executable, str(ROOT / "tools/stage0/qlm_cli.py")])
                command = driver + ["build", str(source), "-o", str(exe)]
                command += ["-j1"] if name == "seed" else ["--target", "win"]
                run(command, env, args.build_timeout, name + " build")
                if not exe.is_file() or not exe.stat().st_size:
                    raise RuntimeError(f"{name}: compiler did not create fresh executable")
                output = run(runner + [str(exe)], env, args.run_timeout, name + " run")
                if output != EXPECTED:
                    raise RuntimeError(f"{name}: expected {EXPECTED!r}, got {output!r}")
                outputs.append(output)
                print(f"PASS: {name} real-helper assertions ({output.decode().strip()})", flush=True)
            if outputs[0] != outputs[1]:
                raise RuntimeError("seed/stage0 outputs differ")
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("PASS: seed and stage0 agree; removal/barriers/backedge/conditionals/missing target/length/idempotence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
