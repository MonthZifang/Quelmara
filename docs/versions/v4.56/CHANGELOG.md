# v4.56 — `--trace` 扩展到 `_opt` 内部 pass

- 日期：2026-11-06
- 任务：v4.48 的 `--trace` 只覆盖 lower/opt/alloc/emit 四阶段边界；
  调优时看不到【每个优化 pass 删了多少指令】。
- 结论：**已扩展**——copy/fuse/dce 三 pass 的 ir 长度逐点输出。

## 实现

`_opt` 主循环的两个 pass 组后各插三行：

```quelmara
_opt_copy(fc, ir, use, ndef)
_tri("    opt: copy ir=", len(ir))
_opt_fuse(fc, ir, use, ndef)
_tri("    opt: fuse ir=", len(ir))
_opt_dce(fc, use)
_tri("    opt: dce ir=", len(ir))
```

`--trace` 输出示例（pin_cross_grow 两函数）：

```
[trace]     opt: copy ir==113
[trace]     opt: fuse ir==113
[trace]     opt: dce ir==113
[trace]     opt: copy ir==85
[trace]     opt: fuse ir==85
[trace]     opt: dce ir==85
```

不带 `--trace` 零输出，行为不变。

## 验证

* RT 7/7、自举 42/42 + 不动点（含 trace 插桩）
* trace 输出正确反映各 pass 后的 ir 长度

## 用途

下次调优/排查时可直接看到【哪个 pass 吃掉了多少指令】——
例如确认 DCE 是否误删（vec 内联第 8 次的 MOV 消失问题
当时若有此观测可立即定位）。
