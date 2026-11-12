#!/usr/bin/env python3
"""Regress stage0's PE stack reservation without rebuilding the full compiler.

Run: python3 tests/test_stage0_pe_stack.py
No Windows/Wine runtime is required: compile a tiny source and inspect PE32+.
"""
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "stage0"))
import qlm_pe


class Stage0PEStackTest(unittest.TestCase):
    def test_small_program_reserves_bootstrap_stack_without_eager_commit(self):
        with tempfile.TemporaryDirectory(prefix="qlm-pe-stack-") as tmp:
            source = Path(tmp) / "hello.qma"
            source.write_text('fn main() { print("stack-header-ok") }\n', encoding="utf-8")
            image, _ = qlm_pe.transpile_win(str(source))
        self.assertEqual(image[:2], b"MZ")
        pe = struct.unpack_from("<I", image, 0x3C)[0]
        self.assertEqual(image[pe:pe + 4], b"PE\0\0")
        optional = pe + 24
        self.assertEqual(struct.unpack_from("<H", image, optional)[0], 0x20B)
        reserve, commit, heap_reserve, heap_commit = struct.unpack_from(
            "<QQQQ", image, optional + 72)
        self.assertEqual(reserve, 16 * 1024 * 1024)
        self.assertEqual(commit, 4096)
        self.assertLess(commit, reserve)
        # These Windows loader heap fields are not the language's VirtualAlloc heap.
        self.assertEqual(heap_reserve, 1024 * 1024)
        self.assertEqual(heap_commit, 4096)


if __name__ == "__main__":
    unittest.main()
