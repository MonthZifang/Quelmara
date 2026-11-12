#!/usr/bin/env python3
"""Small differential executable for the real qlmc lifetime helpers (no full bootstrap).

Python only extracts source and drives compilers. All interval computations run as QMA.
Usage: python3 tests/test_qlmc_liveness.py --baseline build/perf_session_4113/baseline.exe
Use --generate-only to inspect the generated fixture without compiling anything.
"""
from pathlib import Path
import argparse
import os
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ('_end_local', '_end_read', '_rebuild_temp_ends', '_reuse_left_endpoint',
           '_temp_touched', '_temp_start_order', '_opt_mark', '_opt_writes',
           '_ty_is_agg', '_tmp_reg', '_lab_index', '_build_loop_mask')


def extract_block(src, kind, name):
    """Balance braces while ignoring comments and strings, including string braces."""
    m = re.search(r'^' + kind + r'\s+' + re.escape(name) + r'\b', src, re.M)
    if not m:
        raise ValueError(f'missing {kind} {name}')
    start = src.index('{', m.start())
    depth = 0
    quote = False
    comment = False
    escape = False
    for i in range(start, len(src)):
        c = src[i]
        if comment:
            if c == '\n': comment = False
            continue
        if quote:
            if escape: escape = False
            elif c == '\\': escape = True
            elif c == '"': quote = False
            continue
        if c == '/' and src[i:i+2] == '//':
            comment = True
            continue
        if c == '"': quote = True
        elif c == '{': depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0: return src[m.start():i+1]
    raise ValueError(f'unclosed {name}')


DRIVER = r'''
fn ctx() -> FnCtx {
    let f = FnCtx {
        ir: vec[Ir].new(32), vloc: vec[int].new(16), vty: vec[int].new(16),
        vstart: vec[int].new(16), vend: vec[int].new(16), vpin: vec[int].new(16),
        cells: vec[int].new(201), rend: vec[int].new(4)
    }
    let mut i = 0
    while i < 201 { f.cells.push(0) i = i + 1 }
    i = 0
    while i < 12 {
        f.vloc.push(0) f.vty.push(TY_INT) f.vstart.push(0)
        f.vend.push(20) f.vpin.push(0) i = i + 1
    }
    i = 0
    while i < 4 { f.rend.push(-1) i = i + 1 }
    return f
}
fn emit(f: FnCtx, op: int, d: int, a: int, b: int, imm: int) {
    f.ir.push(Ir { op: op, dst: d, a: a, b: b, imm: imm })
}
fn main() {
    let f = ctx()
    // Creation order reversed: v1 is the parent, v2 and v3 are children.
    emit(f, OP_CONST, 2, 0, 0, 9)
    emit(f, OP_CONST, 3, 0, 0, 7)
    emit(f, OP_ADD, 1, 2, 3, 0)
    emit(f, OP_STORED, 1, 3, 0, 8)
    emit(f, OP_NOP, 0, 0, 0, 0)
    f.cells.set(C_SRET, 10)
    _rebuild_temp_ends(f)
    assert(f.vstart.get(1) == 2, "parent real definition")
    assert(f.vend.get(1) == 3, "fused STORE dst read")
    assert(f.vstart.get(2) == 0 && f.vend.get(2) == 2, "child endpoint")
    assert(f.vend.get(3) == 3, "base read")
    let order = _temp_start_order(f)
    assert(len(order) == 4, "dead filtered, hidden sret retained")
    assert(order.get(0) == 2 && order.get(1) == 10, "stable equal-start order")
    assert(order.get(2) == 3 && order.get(3) == 1, "definition order")
    f.vloc.set(2, _tmp_reg(0) + 1)
    f.rend.set(0, 2)
    assert(_reuse_left_endpoint(f, 1, 2, 3) == 1, "binary endpoint")
    let g = ctx()
    emit(g, OP_CONST, 1, 0, 0, 4)
    emit(g, OP_BINI, 2, 1, OP_MUL, 7)
    emit(g, OP_MEMCPYN, 2, 1, 1, 0)
    _rebuild_temp_ends(g)
    assert(g.vend.get(2) >= 2, "memcpy dst byte count read")
    // MUL opcode 5 is not vreg 5, even if that register aliases the left source.
    g.vloc.set(1, _tmp_reg(0) + 1)
    g.vloc.set(5, _tmp_reg(0) + 1)
    g.vstart.set(5, 0) g.vend.set(5, 0)
    g.vend.set(1, 1) g.rend.set(0, 1)
    assert(_reuse_left_endpoint(g, 2, 1, 2) == 1, "BINI b opcode not vreg")
    let touched = _temp_touched(g)
    assert(touched.get(5) == 0, "immediate opcode not touched")
    let h = ctx()
    emit(h, OP_CONST, 1, 0, 0, 4)
    emit(h, OP_LAB, 0, 0, 0, 7)
    emit(h, OP_MOV, 2, 1, 0, 0)
    emit(h, OP_LOAD, 3, 2, 0, 8)
    emit(h, OP_CONST, 4, 0, 0, 1)
    emit(h, OP_CONST, 4, 0, 0, 2)
    _rebuild_temp_ends(h)
    assert(h.vend.get(1) == 20, "cross-block lifetime not shrunk")
    assert(h.vend.get(4) == 20, "multiple definitions not shrunk")
    let ht = _temp_touched(h)
    assert(ht.get(3) > 0, "unused LOAD destination retained")
    let lm = ctx()
    emit(lm, OP_JMP, 0, 0, 0, 901)
    emit(lm, OP_LAB, 0, 0, 0, 900)
    emit(lm, OP_CONST, 1, 0, 0, 1)
    emit(lm, OP_JCMPI, 0x85, 1, 0, 900)
    emit(lm, OP_LAB, 0, 0, 0, 901)
    let mask = vec[int].new(8)
    _build_loop_mask(lm.ir, mask)
    assert(mask.get(0) == 0 && mask.get(1) == 1, "label IDs are not IR positions")
    assert(mask.get(2) == 1 && mask.get(3) == 1, "immediate backedge included")
    assert(mask.get(4) == 0 && mask.get(5) == 0, "forward branch not a loop")
    print("liveness-helper-ok")
}
'''


def generate(src):
    funcs = '\n\n'.join(extract_block(src, 'fn', n) for n in HELPERS)
    ir = extract_block(src, 'struct', 'Ir')
    # Project only fields used by the real helpers; avoid unrelated parser/runtime structs.
    full_ctx = extract_block(src, 'struct', 'FnCtx')
    fields = set(re.findall(r'\bfc\.(\w+)', funcs))
    lines = []
    for line in full_ctx.splitlines():
        if re.match(r'\s*(?:' + '|'.join(sorted(fields)) + r')\s*:', line):
            lines.append(line.split('//')[0].rstrip())
    ctx = 'struct FnCtx {\n' + '\n'.join(lines) + '\n}'
    constants = dict(re.findall(r'^const\s+(\w+)\s*=\s*([^\n]+)', src, re.M))
    needed = set()
    text = funcs + DRIVER + ctx + ir
    while True:
        new = {n for n in re.findall(r'\b[A-Z][A-Z0-9_]*\b', text) if n in constants} - needed
        if not new: break
        needed |= new
        text += '\n' + '\n'.join(constants[n].split('//')[0] for n in new)
    consts = '\n'.join('const ' + n + ' = ' + value for n, value in constants.items() if n in needed)
    return 'module liveness_helpers\n' + consts + '\n' + ir + '\n' + ctx + '\n' + funcs + '\n' + DRIVER


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline', type=Path)
    p.add_argument('--out', type=Path, default=ROOT / 'build/liveness_helpers')
    p.add_argument('--generate-only', action='store_true')
    p.add_argument('--timeout', type=int, default=180)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    fixture = a.out / 'helpers.qma'
    fixture.write_text(generate((ROOT / 'bootstrap/qlmc/qlmc.qma').read_text()), encoding='utf-8')
    print(f'generated {fixture}', flush=True)
    if a.generate_only: return 0
    if not a.baseline: p.error('--baseline required unless --generate-only')
    env = os.environ.copy()
    env.setdefault('WINEDEBUG', '-all')
    env.setdefault('WINEDLLOVERRIDES', 'winemenubuilder.exe=d')
    outputs = []
    for name in ('stage0', 'baseline'):
        exe = (a.out / (name + '.exe')).resolve()
        cmd = ([sys.executable, str(ROOT / 'tools/stage0/qlm_cli.py')] if name == 'stage0'
               else (['wine'] if os.name != 'nt' else []) + [str(a.baseline.resolve())])
        cmd += ['build', str(fixture.resolve()), '-o', str(exe)]
        if name == 'stage0': cmd += ['--target', 'win']
        else: cmd += ['-j1']
        r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=a.timeout)
        if r.returncode:
            print(r.stdout + r.stderr)
            raise RuntimeError(f'{name} build rc={r.returncode}')
        run = subprocess.run((['wine'] if os.name != 'nt' else []) + [str(exe)],
                             cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
        print(name, 'rc=', run.returncode, 'stdout=', repr(run.stdout), flush=True)
        if run.returncode or run.stdout.strip() != 'liveness-helper-ok':
            print(run.stderr)
            raise RuntimeError(f'{name} helper assertions failed')
        outputs.append(run.stdout.replace('\r\n', '\n'))
    assert outputs[0] == outputs[1], 'compiler execution results differ'
    print('PASS: stage0 and baseline helper execution agree')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
