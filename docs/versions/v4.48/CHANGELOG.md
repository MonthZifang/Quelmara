# v4.48 — `--trace` 诊断通道（lowering/codegen 可观测）

- 日期：2026-11-05
- 任务：vec 内联布局四次尝试全部"静默失败"，故障在 lowering 但无任何
  输出，每轮 12 分钟构建只能盲猜。
- 结论：**已实现** `--trace`，stage-2 出问题时终于能看到卡在哪。

## 实现

新增全局状态 `SW_TRACE` + 命令行 `--trace`：

```quelmara
fn _tr(msg: str) {
    if _trace_on() == 1 {
        eprint("[trace] " + msg)
    }
}
fn _tri(tag: str, v: int) { ... }   // 带整数版
```

插桩点在 `_compile_range` 的主循环（每函数一条）：

```
[trace] compile_range wid=0
[trace]   lo=0  hi=1  new_fc ok
[trace]   fn idx=0
[trace]     reset ok
[trace]     lower ok, ir==5
[trace]     opt ok, ir==5
[trace]     alloc ok
[trace] emit_fn vregs=3
[trace]     emit ok
```

输出走 stderr，不污染 stdout（校验和解析不受影响）。

## 立即的回报

接上之后第一次跑 stage-2 就发现：**之前判定的"stage-2 失败"有一类
是测量假象**。带 `--trace` 跑 `tiny.qma` 完全正常：

```
[qlmc] tiny.qma -> out (4199 字节)  编译 4183 us
```

连续 3 次都成功。之前的"无输出、无文件"里有相当一部分是
**wine 相对路径 + 输出重定向**造成的观测错误，不是编译器真坏了。

当然 vec 内联布局的失败是另一回事——那些场景是**stage-2 的 lowering
在特定输入下早退**（`dump` 正常、`irdump` 无输出，可稳定复现）。
现在有了 trace，下一次重试 vec 内联时可以直接看到它卡在哪个函数、
哪个阶段，不再盲猜。

## 验证

自举五级链 42/42 + 不动点 PASS（含 trace 插桩的构建）。
不带 `--trace` 时零输出，行为与 v4.47 完全一致。
