# v3.73 — 泛型单态化：收掉 §7.44，覆盖率 **69/69**（分母全绿）

- 日期：2026-11-02
- 任务：`std/gen` 是 qlmc 覆盖率 68/69 里最后一个失败项（§7.44）。
  本版实现泛型单态化，**`std/` 下每个模块 qlmc 都编得过**。
- 影响面：`bootstrap/qlmc/qlmc.qma`（约 480 行）、
  `tests/selfhost/s40_generic.qma`（新增差分夹具）、
  `tests/qlmc_test.py` + `tests/bootstrap_test.py`（wine 包装）、
  `tools/dev/qlmc_coverage.py`（基线 68 → 69）
- 代码改动：约 510 行

## 做法：记 token 区间 → 重新 parse

**不复制节点**。qlmc 的节点表是平坦数组，复制函数体要按 `E_*` 逐类判断
`a`/`b`/`c`/`n`/`slot`/`nx` 里哪些是 node id —— 判错一处就是静默错编。

改为：

1. `_fn` 遇到 `fn 名[T]` / `fn 名[T: 约束]`：记下 **token 区间**，跳过体；
2. `_expand_all` 扫 `E_CALL` 节点，用 `_ty_of_expr` 推实参类型，`_gt_infer`
   从 `T` 或 `vec[T]` 推出实参；
3. `_expand_generic` 把区间切片（**去掉 `[T]` 那段**）、设好 `T` 绑定、
   调 `parse` —— 得到的就是一个普通具体函数，语义天然正确；
4. 特化副本**改名**（`mx__int` / `mx__f64`，与 stage-0 同款），
   并把**调用点改写成新名字**。

存哪：`static_word`（parse 期单线程）。`P` 已 16 字段、`Fn` 8 字段、
`FnCtx` 不能加字段（v3.62 教训），所以模板表放静态字区
`SW_GT_BASE = 8`，每模板 4 槽 `(nid, tok_lo, tok_hi, tname_nid)`，
`GT_STRIDE = 4`，`GT_MAX = 12`（`std/gen` 9 个），`SW_GT_EXPANDING = 63`
（必须在表区间 `8+12*4=56` 之外）。

## 顺带修：三处"报错文本与真因无关"的越界

这四处都是**既有缺陷**，只是从没有代码路径同时满足触发条件：

| 位置 | 症状 | 真因 |
|---|---|---|
| `_vtypes_elem` | `vec index out of bounds` | 只判上界不判下界，未登记的 vec 码直接索引 `stt` |
| `_new_fc` / `_fc_reset` | 同上 | `cells` 只有 10 格，而 `C_FMOD = 200`；`_fn_index` 直接 `cells.get` 不经 `_cell_set` |
| `_ty_of_expr` | `未定义变量 vs` | 它调 `_var_id` —— 那是"未定义变量"的**报错路径**（末尾 `exit(2)`），在 lowering 之前的推断期调它，把正常情况报成编译错误 |
| `_expand_generic` 切片 | `期望标点 #26` | "见 `[` 就跳"把形参的 `vec[T]` 也删了，只该跳形参表之前那个 |

## 验收（三条全绿，缺一条就是假能力）

| 判据 | 结果 |
|---|---|
| `std/gen` 编得过 | ✅ 覆盖率 **69/69**（分母全绿，`BASELINE` 68 → 69） |
| 差分夹具逐字节对照 stage-0 | ✅ `s40_generic` 输出 `9 2.5 4 2.5 alpha 42 14 21`，**8/8 相同** |
| 推导失败有明确诊断 | ✅ `qlmc: 推不出泛型实参（名字）`，`exit(2)` |
| 全套差分回归 | ✅ **92/92**（含新增 s40_generic） |
| 文档门禁 | ✅ `check_docs` / `check_names` / `check_origin` / `check_static_words` |

`s40_generic` 覆盖：同一模板 int/f64 两实例、`[T: Ord]` 约束形态、
`vec[T]` 一元推导、体内自调用、特化副本互调。

## 本版**未做**（明确留给后续，不声称支持）

* **约束违反检查**：`[T: Ord]` 的约束本版只跳过语法，不校验。
  给 `gen_min` 传 struct 不会在编译期报错（stage-0 会）。
* 泛型 struct / enum / method、多类型参数、显式实例化 `f[int](...)`。
* `lib` 模式无调用点时按 `int` 展开全部模板（保证库里不是空的），
  用户用别的类型时在自己的编译单元里展开对应实例 ——
  这是单态化语义，不是"一个实例通吃"。

## 顺带修：三个测试脚本的 wine 包装

Linux 上 `binfmt_misc` 的 `MZ` handler 会把 `argv[0]` 重复塞进去，
qlmc 于是把 `build` 当成源文件名，报"打不开源文件 build"（v3.63 已知）。
`tools/dev/qlmc_coverage.py` 早已修过，本版把同样修法补到
`tests/qlmc_test.py` 与 `tests/bootstrap_test.py`：

```python
def _exe_runner(exe):
    if os.name == "nt":
        return [exe]
    wine = shutil.which("wine")
    ...
    return [wine, exe]
```

修之前两个脚本在 Linux 上是**全红**（`PASS=1 FAIL=47` / stage-2 FAIL），
但那是环境问题、不是编译器问题 —— 这类"环境伪装成缺陷"最难分辨，
所以三个脚本现在用同一份实现。
