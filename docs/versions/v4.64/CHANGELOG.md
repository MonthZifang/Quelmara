# v4.64 — qlmc ELF 后端 DIV/MOD 2^k 变换修复（正确性）

- 日期：2026-11-07
- 性质：编译器代码修正（自举产物 `build/qlmc.exe` 重新编译生效）

## 背景

v4.63 起 qlmc 的 ELF64 后端已能跑全部 76 项真实基准（posix CI 矩阵已把它和
C/C++/Go/Rust/Zig/Nim/Fortran 同台对比）。`_emit_divc` 里有一段
"除数为 2 的幂 → 位运算序列"的优化（v4.63 引入）：

```
t = (x sar 63) & (d-1)      # 负数 = d-1，非负 = 0
DIV: dst = (x + t) sar k
MOD: y = x + t; r = x - ((y sar k) shl k)
```

## 缺陷（本版修复）

原序列里 MOD 分支的 "t 备份" 指令 `mov rdx, rax` 被错编码成
`0x48 0x89 0xD0`，实际是 `mov rax, rdx`（ModRM 字节写反：
`mod 11, reg=RDX, rm=RAX` 而非 `mod 11, reg=RAX, rm=RDX`）。结果 `rdx`
里的垃圾值泄漏进余数计算，导致 `x % 2` 对**正奇数**返回 `-1`、对负奇数返回
`+1` 的随机正确值（取决于 rdx 当时是否为 0）。典型症状：

- `17 % 2` → `-1`（应为 `1`）
- `b13_collatz`（含 `n/2`、`n%2`）在 qlmc ELF 下**死循环**（余数错 → 序列不收敛到 1）
- `b38_prime` / `b57_pow_mod` / `b75_fib_matrix` 校验和与 C 不一致

DIV 分支不走这条 `mov rdx,rax`，所以纯除法（如 `b13` 的 `n/2`）一直正确，
掩盖了问题。

## 修复

- MOD 分支 `mov rdx, rax` 改为正确 ModRM：`0x48 0x89 0xC2`
  （`mod 11, reg=RAX, rm=RDX` = 目标 rdx，源 rax）。
- 同时把两处 `add rax, rcx`（ModRM `0xC0` = add rax,rax）修正为
  `0xC8`（= add rax,rcx）。

## 验证

- 单元：`17/2=8` `17%2=1` `-17/2=-8` `-17%2=-1` `300000/2=150000`
  `300000%2=0`；范围压测 `i ∈ [-100000,100000)` 全部满足
  `(i/2)*2 + (i%2) == i`。
- 回归：qlmc ELF 全量 73 项基准与 C **逐项校验和一致（0 mismatch）**，
  含此前不一致的 `b13` / `b38` / `b57` / `b75`。

## 文档

- `bench/speed/README.md`：澄清 "qlmc 还没有 ELF 后端" 等过期表述
  （ELF 后端自 v3.94 起已能跑真实基准并在 posix 矩阵中启用），基准数
  由 "十个" 更新为 75 项、语言接入状态按 v4.64 重列。

## 版本节奏

v4.64 为纯正确性修复，不引入新特性。下一步进入多语言源码覆盖扩展
（go/c#/c++/py/rust/java/zig/ada/fortran/d/nim × 75 项），每补一种语言
即一个版本、一次提交、推到 GitHub。
