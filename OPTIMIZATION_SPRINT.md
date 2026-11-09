# Quelmara Performance Optimization Sprint v1.0

**Mission:** Achieve #1 performance ranking over C/C++  
**Current Version:** 4.85.0 (1/99 iterations)  
**Target Version:** 5.0.0 upon achieving first place  

---

## 📋 Iteration Log

### ✅ Iteration #1 - Auto-Vectorizer v1 (4.84.0 → 4.85.0)

**Date:** 2026-11-09  
**Status:** Complete & Pushed  
**Changeset:** `aa8aeeb` on master branch

**Deliverables:**
1. ✅ SIMD IR operations (vload32/64, vmul, vadd, vdot, vhsum)
2. ✅ Pattern detection for reduction loops
3. ✅ Integration into optimization pipeline
4. ✅ Changelog & detailed report generated
5. ✅ Code pushed to GitHub

**Expected Impact:**
- `b1_int`: 4.28× slower → ~1.5× (theoretical 12× speedup)
- `b8_threads1`: 4.28× slower → ~1.5×
- `b4_array`: 2.85× slower → ~1.2×

**CI Validation Status:** ⏳ Awaiting benchmark run

---

### 🔜 Iteration #2 - Loop Dependency Resolution (4.85.0 → 4.86.0)

**Status:** Pending CI validation  
**Priority:** High

**Objectives:**
1. Resolve modulo operator dependency chains
2. Map to ARM NEON instructions
3. Optimize lane counts per architecture

---

## 🎯 Target Benchmarks

Based on analysis of 75 benchmarks in `bench/speed/`:

### Primary Targets (Critical Gaps)

| Benchmark | Description | Current vs C | Strategy | Expected Ratio |
|-----------|-------------|--------------|----------|----------------|
| `b1_int` | Integer arithmetic 20M ops | 4.28× slower | 8-way AVX2 | <1.5× |
| `b8_threads1` | Single-thread 160M ops | 4.28× slower | SIMD + scheduling | <1.5× |
| `b4_array` | Array traversal 2M elems | 2.85× slower | Burst loads/stores | <1.5× |
| `b7_sort` | Quicksort 200K items | 1.60× slower | Vectorized partition | <1.3× |
| `b8_threads4` | 4-thread parallel | 1.45× slower | Task parallelism | <1.2× |

### Secondary Targets (Minor Improvements)

| Benchmark | Current vs C | Strategy |
|-----------|--------------|----------|
| `b6_hash` | **0.91× faster** ✅ | Maintain lead |
| `b2_float` | **1.00× equal** ✅ | Stabilize AVX2 path |
| `b5_string` | 1.33× slower | String SIMD ops |
| `b9_json` | 3.91× slower | JSON parse vectorization |

### Long-term Targets (Major Overhaul Needed)

| Benchmark | Gap to C | Required Work |
|-----------|----------|---------------|
| `b3_recursion` | 2.00× | Tail call optimization |
| `b1_int (Linux)` | 1.27× | GCC-specific tuning |
| macOS ports | N/A | Mach-O backend |

---

## 🔬 Methodology

### Performance Measurement Protocol

1. **Min-of-N Runs:** All timing measurements take minimum of 3-5 runs
2. **Checksum Verification:** All benchmarks produce identical output across languages
3. **CI Authority:** Official numbers from GitHub Actions runners (EPYC 9V45, Apple M-series)
4. **Local Validation:**本机测试仅用于快速迭代验证，不对外引用

### Optimization Hierarchy

```
Level 1: Instruction Selection
  └─ Generate optimal opcode sequences per target

Level 2: Register Allocation
  └─ Maximize register reuse, minimize spills

Level 3: Loop Optimization
  ├─ Unrolling (compile-time constant bounds)
  ├─ Vectorization (SIMD lane utilization)
  └─ Induction variable elimination

Level 4: Memory Access
  ├─ Prefetching hints
  ├─ Alignment guarantees
  └─ Cache-aware data layout

Level 5: Parallelism
  ├─ Task-level threading
  └─ SIMD within threads
```

### Architecture Coverage Roadmap

**Phase 1 (Current):** x86_64 with AVX2
- 256-bit YMM registers
- up to 8×int32 or 4×f64 per operation
- Ports: PMULUDQ(0,5), PADDD(0,1,5)

**Phase 2 (Q1):** AArch64 with NEON
- 128-bit initial, scale to 256-bit SVE2
- ARM-specific instruction scheduling
- Test on Apple Silicon (macOS runner)

**Phase 3 (Q2):** Backends maturity
- Windows PE COFF with full RTTI-free linking
- Linux ELF64 with dynamic loading support
- Mach-O for macOS/iOS (blocked by backend gap)

---

## 📊 Version Control Strategy

### Incremental Updates

Each iteration:
1. **Analyze** current performance gaps
2. **Implement** targeted optimizations
3. **Document** changes in changelog
4. **Push** to main branch
5. **Validate** via CI benchmarks
6. **Bump** version number

### Version Schema

`major.minor.patch` where:
- **minor** increments each iteration (max 99 before major bump)
- **patch** for hotfixes (not counted against iteration limit)
- **major** bumps after reaching target (#1 ranking)

**Current Progress:** 4.85.0 = 85/99 iterations remaining

---

## 🚦 Milestones

| Milestone | Version | Criteria | Status |
|-----------|---------|----------|--------|
| M1: Auto-vectorizer foundation | 4.85.0 | SIMD ops implemented | ✅ Done |
| M2: Close primary gaps <1.5× | 4.90.0 | Top 5 benchmarks under 1.5× | ⏳ In progress |
| M3: Competitive parity ≤1.1× | 4.95.0 | All benchmarks within 10% of C | ⏳ Planned |
| M4: First place <1.0× | 5.0.0 | Outperform C in majority categories | ⏳ Future |

---

## 🛠️ Toolchain

### Git Workflow

```bash
# Local development
git checkout -b feat/vectorize-v2
# ... make changes ...
git add .
git commit -m "feat(v4.86): ..."

# Push and sync
git push origin feat/vectorize-v2
# ... PR review ...
git merge --no-ff feat/vectorize-v2 -m "Auto-merge to master"
git push origin master
```

### CI Triggers

- **Manual:** `gh workflow run bench.yml`
- **Auto on push:** `.github/workflows/bench.yml` (push to master, changes in `bench/**`, `bootstrap/qlmc/**`, `tools/stage0/**`)
- **Scheduled:** Weekly Monday 02:00 UTC+8

---

## 📝 References

- [Main README](./README.md)
- [Compiler Documentation](./docs/04-compiler.md)
- [Benchmark Results](./bench/speed/RESULTS.md)
- [Current Status](./docs/06-status.md)
- [Version History](./docs/versions/)

---

**Last Updated:** 2026-11-09  
**Author:** Qoder (AI Optimization Agent)  
**Next Review:** After CI benchmark validation completes
