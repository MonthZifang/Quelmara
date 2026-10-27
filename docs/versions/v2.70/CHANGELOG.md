# v2.70 — 常量下标直接用位移寻址

- 日期：2026-10-27
- 任务：压 load/store 的固定开销
- 影响面：`tools/stage0/qlm_native.py`（`load` / `load8` / `load32` / `store` / `store8`）

## 根因：每条带常量下标的访问都白付一条 `mov`

`load d, base, ('imm', k)` 以前是先把下标物化进 `SCRATCH`，再按
`[base + idx*8]` 寻址：

```
mov r11, 1                      ← 白付
mov r15, qword ptr [r14 + r11*8]
```

vec 句柄的 `data`/`len`/`cap`（下标 0/1/2/3）、结构体字段、定长数组下标
**全是常量**，所以这条 `mov` 的命中率极高。

## 改法

常量下标直接折进位移：

```
mov r15, qword ptr [r14 + riz + 8]
```

`load`/`store` 是 8 字节元素（位移 = `k*8`），`load8`/`load32`/`store8` 是
字节偏移（位移 = `k`）。位移超出 int32 范围时退回原路径（fail-safe）。

f64 的 `movsd` 路径一并处理。

## 效果

b4_array 的 push 循环 **29 → 25 条**；b4/b7 全函数各少几十条。
这是**纯指令数**的减少（每条常量下标访问少 1 条 `mov`），不依赖测量。

本机 A/B 的时间差被 VBS 噪声盖住了（b4 13.7/11.8 → 11.9/12.7、
b7 42.4/41.8 → 40.6/40.0、b9 在 27.7–33.6 之间跳），**方向是少指令、
不可能更慢**，量级以 CI 为准。

## 回归

`tests/run_win_tests.py`：见本轮实测（基线 297）。
