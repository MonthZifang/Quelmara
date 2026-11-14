# v4.121 — 修复 `&vec` 取址被复制传播塌缩（&T 配套正确性修复）

- 日期：2026-11-14
- 任务：修复 v4.120 `&T` 的 `&vec[T]` 路径在 stage-0 原生后端的段错误，使引用语义
  覆盖 vec（vec 内联布局的前置）。**正确性修复，不改既有基准跑分。**
- 影响面：stage-0 优化器（`qlm_opt.py` 复制传播）、测试。

## 根因（第 10–11 轮 debug 实证）

`&vec` 跨调用 push/grow 在 stage-0 原生后端段错误（qlmc 侧一直正确）。定位：
- `addrslot` 发射本身正确（源 vreg 确在 force_mem 帧槽）。
- 但 **`opt_copy_prop` 把被取址变量别名塌缩**：`let a = vec.new(…)` 降级为
  `MOV a, handle`，复制传播将 `a` 别名到 `handle` 并**删掉定义 MOV**，而 `addrslot`
  源仍指向 `a` → `a` 的帧槽从未被写 → `&a` 读到垃圾 → 段错误。
- `&int` 不触发：int 实参多为常量/简单变量，未形成"被取址变量 = 可塌缩 MOV 目标"。

## 改动

| 文件 | 改动 |
|---|---|
| `tools/stage0/qlm_opt.py` | `opt_copy_prop` 收集 `addrslot` 源（被取址 vreg），**禁止将其作为别名键塌缩**——定义 MOV 保留、被取址变量始终是被写过的稳定槽 |
| `tests/s_ref.qma` | 追加 `&vec[int]` 用例：`vfill(v:&vec[int],n)` 跨调用 push+grow，调用方经原句柄 get |

## 验证

| 项 | 结果 |
|---|---|
| s_ref 差分（含 &vec grow） | stage-0 / qlmc 逐字节一致（…0 38 20） |
| 全套 qlmc_test | **PASS=126 FAIL=0**（含 selfhost 42、-j1==-j4、ref 夹具含 &vec） |
| 自举对拍四件套 | lexdiff 388/0、parsediff 292/0、irdiff 127/0、emitdiff 10/0 |
| 全量 76 项 ×3 轮 | **76/76 与 C 校验一致**；几何平均读数 1.630（v4.120 1.637，产物逐字节相同故为测量噪声）；≤1.1× 19 项 |
| 源码级冷缓存严格自举 | **PASS**（`QLM_NO_CACHE=1`）：stage-0 编 stage-1 864.6s；stage-2 785408 字节；42/42 组逐字节一致；错误路径干净退 2；stage-2==stage-3 不动点成立 |
| 基准产物比对 | b28/b68 等与 v4.120 **逐字节相同**（qlmc 源码未变，改动只在 stage-0 优化器） |

## 说明

- 复制传播改动**只影响含 `addrslot` 的函数**（即用了 `&T` 取址）；既有基准/代码无
  `addrslot`，`addr_taken` 为空，行为与改前逐字节一致——故跑分不变。
- 这是 vec 内联布局的前置修复：`&vec` 正确后，才能按 `VEC-INLINE-PLAN.md` 用引用
  传播 grow 的新块地址，做 `[len][cap][data…]` 内联布局。
