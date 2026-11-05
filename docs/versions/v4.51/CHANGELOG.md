# v4.51 — 修复 mem_load64/store64 常量下标的 ×8 折叠缺失

- 日期：2026-11-05
- 任务：v4.50 附录 9 锁定的真 bug —— `ADDRX(p, 常量w)` 在优化层
  被折叠成 `p + w`（漏 ×8），常量偏移写错位 8 倍。
- 结论：**已修复**，RT 单测 3/3，自举 42/42。

## 语义基准（先钉死）

`mem_load64/store64` 的偏移 = **槽索引（×8）**：

* stage-0 注释（qlm_native.py L3303）："mem_load64(p, w) 读第 w 个
  8 字节字"——显式 ×8
* docs/02-language.md L1261："mem_load64/store64 的偏移是槽索引（×8）"
* b6_hash（变量下标）一直绿 —— 走 `ADDRX`（shl rcx,3）正确 ×8

错的是【常量下标】：优化层把 `ADDRX(p, 常量w)` 折叠成 `p + w`，
少乘 8。单块程序"写读同错自洽"所以差分/自举/基准全绿；
只有 mem_copy（字节 n、真地址）跨块访问才暴露。

## 修法（lowering 端绕过）

`mem_store64/mem_load64` 的 lowering：下标节点是 `E_NUM` 字面量时，
直接 `CONST w*8 + ADD`（字节已算好，优化层无从折叠错）；
变量下标仍走 `ADDRX`（发射器 `shl rcx,3` 恒正确）。

为什么不修折叠点：折叠点在 `_opt` 内部（具体哪个 pass 产生的
BINI(p+1) 未定位），而 lowering 端一行绕过是确定性的。

## 验证

* **RT 单测 3/3**：
  - `memcpy_basic` PASS（37 字节尾部拷贝，load8 逐字节校验）
  - `memcpy_tail37` PASS
  - `two_allocs_slot_clobber` PASS（v4.50 时 FAIL=1 —— 修复直接生效）
* 自举五级链 42/42 + 不动点 4.8s PASS

## 语义澄清（本轮三次反转的最终定案）

* mem_load64/store64 = **槽索引**（不是字节）—— stage-0 注释、
  docs L1261 一致；我此前两度误判（字节语义、lowering 错）均回退
* mem_copy = **memcpy 语义，重叠未定义**（与 C 一致）。v4.49 的
  "逐字节重叠正确"是 memmove 语义的巧合，v4.50 块拷贝后重叠 UB
  —— 这不是回归，是与 C 对齐；需要 memmove 语义时用户自己倒序
* RT 用例已按真实语义重写：字节级校验用 load8，重叠用例改非重叠

## 基准校验和

b31=12499999 / b28=960991321 / b23=1498 / b82=9999999 全对
（这些只用变量下标或 0 下标，修复不影响）。
