# v2.78 — 修 CI 剩下两处红灯（x509 的 pub / 声明级对拍的输出顺序）

- 日期：2026-10-27
- 任务：让 CI 的 windows job 走到全绿（性能改动见 v2.76）
- 影响面：`std/x509.qma`、`bootstrap/parser/qlm_parse.qma`、`docs/03-stdlib.md`

v2.77 修好 gzip 那一步之后，CI 才露出后面两步的红。两处都是**老问题被前一步
挡住**，不是这两版改坏的。

## 一、`x509_san` / `x509_validity` 少了 `pub`

和 `zlib_decode` 同一个形状：`tests/x509_chain_test.py` 生成的探针跨模块调用，
撞上 v2.43 的可见性检查。

```
SyntaxError: _x509_chain_probe.qma: 引用了非 pub 声明（2 处）：
  'x509_san' <- x509.qma、'x509_validity' <- x509.qma
```

补 `pub` + `///`。公开函数 530 → **532**。本机 `x509_chain_test` → **PASS=13 FAIL=0**。

顺手做了一次全量扫描（std/ 里所有非 pub 声明 × 所有 import 了该模块的源文件），
除这两条外没有第三处。

## 二、声明级 AST 对拍：输出顺序不一致

```
[FAIL] tests/t148_f64_xmm.qma: oracle 5 行 / parser 5 行
       第 1 行：want 'struct|Pair|a:float,b:float'  got 'fn|harmonic|(int)|float'
```

**行数一样、内容一样，只是顺序不同**。oracle（`tools/dev/astdecl.py`）的输出是
**struct/enum 全部在前、fn 全部在后**（它按 `order` 遍历声明、再单独遍历 `fns`），
而 `bootstrap/parser/qlm_parse.qma` 是"读到哪打到哪"。

只要源码里 struct 写在 fn **后面**（`t148_f64_xmm.qma` 就是：先 `fn harmonic`，
后面才 `struct Pair`），两边行序就对不上。之前 199 个文件全过，是因为它们的
struct 恰好都在 fn 前面 —— **顺序碰巧一致**，不是真的一致。

**改法**：函数签名行先排队（`queue_fn` 塞进 `ds["fnq"]`，用 `map[str]str` 当
队列 —— 这个文件的跨函数状态都走 map），文件末尾一次刷出。`@derive` 派生行的
`pending` 队列改成往 `fnq` 里追加，所以"派生函数排在第一条用户函数之前"这个
既有约定不变。

本机：`parsediff` **PASS=199 FAIL=2 → PASS=201 FAIL=0**。

## 三、坑：改 .qma 源码要用 Edit，别用 Python 的 `open(..., "w")`

第一版用 Python 读改写 `qlm_parse.qma`，`open(p, encoding="utf-8")` 会把 CRLF
**读成 LF**，再用 `newline=""` 写回去就是纯 LF —— diff 从 31 行变成 **3395 行**
（整个文件重写）。用二进制读写或 `newline="\r\n"` 才对。

## 四、还剩什么

- **Linux job 仍然红**：自举对拍 `PASS=0 FAIL=297` —— `--target native` 产出的
  ELF 跑起来 `rc=1`、零行输出。`--target` 已经按宿主选对了，是 **ELF 后端本身
  的 bug**，本机没有 Linux 环境（WSL 被沙箱拦），只能靠 CI 迭代。
- **perf job 的门禁自测**在 runner 上报 `FileNotFoundError`（本机 12/12 全过），
  疑与环境有关，未定位。
