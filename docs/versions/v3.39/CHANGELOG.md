# v3.39 — 补 `vec.pop()`：qlmc 覆盖率 39 → 43

- 日期：2026-10-30
- 任务：用户要求"继续"；推进"编译器核心改用自研语言"
- 影响面：**核心（Quelmara 源码）** `bootstrap/qlmc/qlmc.qma`
  （vec 方法补 `pop`），基线从 39 上调到 43
- 版本：按 `00-convention.md` §5.1 建版本目录

## 起点

v3.38 的 CHANGELOG 把下一步定为"vec 方法不全（4 个模块，低风险）"。

先查这四个模块（`ds` / `json` / `path` / `regex`）实际用了哪些 vec 方法：

```
.push(  .get(  .set(  .pop(     ← 四个模块都用到 .pop
```

而 qlmc 的报错信息写着"只支持 .push / .get / .set / .len / .clear" ——
**`.clear()` 已支持，缺的就是 `.pop()`**。

## 实现

`vec.pop()` 的语义照 stage-0 的 `__vec_pop`：

```c
if (v->len <= 0) qlm_vec_fail();
v->len--;
return *(int64_t *)(v->buf + v->len * v->esz);
```

qlmc 侧用现有 IR 拼出来：

1. 取 `len`（`h[1]`）；
2. **`len <= 0` 必须 fail-fast** —— 与 stage-0 一致，不能静默读越界；
3. `nl = len - 1`，写回 `h[1]`；
4. 读 `buf[nl]`（聚合元素返回地址，标量返回加载值）。

空 vec 的检查复用 `_vec_check` 那套"条件反写 + `OP_EXIT 1` 死路"的
模式（与 v2.46 的 `_addr_index` 同构）。

## 验证

| 表达式序列 | stage-0 | qlmc |
|---|---|---|
| push(10,20,30) 后 `pop()` | 30 | 30 |
| 再 `len(v)` | 2 | 2 |
| 再 `pop()` | 20 | 20 |
| 再 `len(v)` | 1 | 1 |
| `get(0)` | 10 | 10 |

**空 vec 上的 pop**：qlmc 产物退出码 1、无输出 —— fail-fast 生效，
不是静默读越界。

夹具 `t183_qlmc_vecpop.qma` 还覆盖：pop 后继续 push、push/pop 交替、
`vec[str]` 上的 pop（非聚合元素走同一条路径）。

## 结果

| 指标 | v3.38 | v3.39 |
|---|---|---|
| **qlmc 覆盖 `std/`** | 39 / 70 | **43 / 70** |

比预期多解开了 1 个模块（那 4 个用 `.pop` 的模块之外，还有别的模块
是被 `.pop` 之外的连带原因卡住，pop 修好后也顺带通了）。

基线已上调到 43（门禁自己提示的）。

## 回归

全量 Windows 回归 PASS=356 FAIL=0 SKIP=0（v3.38 是 355，新增 1 条
qlmc_vecpop；	183 另计入 parsediff 的 238 项）。

## 剩余 27 个失败的分布

| 数量 | 原因 | 难度 |
|---|---|---|
| 4 | `vec[vec[T]]` 类型码撞区间（§7.18） | **高**（要重排编码，34 处比较） |
| 2+2 | `xmm_load` / `xmm_mov` | 中（SIMD 寄存器） |
| 6+ | `tcp_listen` / `udp_*` / `file_size` / `wall_ms` / `args` | **高**（要接 Winsock/文件 API） |
| 1×N | 语法子集缺口（`期望标点` / `const 初值` / `未知类型`） | 中 |

**下一步**：`vec[vec[T]]` 的收益最大（4 个模块，且是 stage-0 与 qlmc
的**真实**差异 —— v3.38 已核实 stage-0 支持、qlmc 不支持）。它需要
重排类型编码 + 改 34 处范围比较，值得单独一版专门做。

## 一个持续有效的做法

从 v3.36 起，每个新内建/方法都做 **stage-0 / qlmc 双向对拍**，并且
夹具覆盖边界（空 vec、`n=0`、低字节截断…）。这个做法抓到过两个真实
bug（`mem_load32` 宽度没分派、`mem_chr` 的 REX 字节写错），都不是
"能跑就以为对了"能发现的。
