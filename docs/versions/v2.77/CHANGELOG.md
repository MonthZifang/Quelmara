# v2.77 — `zlib_decode` 补 `pub`（修 CI windows job 从 v2.72 起一直红）

- 日期：2026-10-27
- 任务：修 CI 红灯（不是性能）
- 影响面：`std/gzip.qma`（一个关键字）、`docs/03-stdlib.md`（重新生成）

## 症状

CI 的 windows job 从 v2.72 起一直红在「gzip 解码互操作」这一步：

```
SyntaxError: _inflate_probe.qma: 引用了非 pub 声明（1 处）：'zlib_decode' <- gzip.qma
```

`tests/gzip_inflate_test.py` 会临时生成一个探针程序去调 `std/gzip` 的
`zlib_decode`，而 v2.43 加 `pub` 可见性检查时这条声明漏了 `pub` —— 同模块内
调用不受影响（`gzip_decode` 自己就在 `std/gzip.qma` 里），所以本机 86 条断言
一直绿，只有**跨模块**的探针会撞上。

## 改法

`fn zlib_decode` → `pub fn zlib_decode`，并补 `///`（公开声明必须带文档，
`gen_stdlib_doc.py --require-doc` 会拦）。`docs/03-stdlib.md` 重新生成：
公开函数 529 → **530**。

本机：`python tests/gzip_inflate_test.py` → **PASS=86 FAIL=0；损坏输入拒绝 5/5**。

## 教训

**"本机全绿"不等于"CI 全绿"**：这条测试的探针是跨模块的，只有它会触发
可见性检查，而它排在 windows job 的第六步 —— 前面五步全绿的时候红灯看起来
像是"最近改坏的"，实际是 v2.43 就埋下的。加可见性规则时应该**全量 grep
一遍"别的模块引用了哪些非 pub 声明"**，而不是等 CI 一条条撞。
