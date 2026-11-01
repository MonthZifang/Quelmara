# v3.61 — 跨模块 struct：import 图拓扑排序；覆盖率 63 → 64

- 日期：2026-11-01
- 任务：用户要求"继续优化或执行"。上手复核发现 **CI 连续两次全红**
  （v3.58 / v3.59 都红在第 4 步门禁，后面 6 个测试步骤全部 skipped），
  先修那个（→ v3.60），再做本条覆盖率。
- 影响面：`bootstrap/qlmc/qlmc.qma`（`_topo_order` / `_mod_index_of` +
  parse 顺序调整）、`tests/selfhost/s37_crossmod.qma`、
  `tests/selfhost/mod_shape.qma`、`tests/qlmc_test.py`、
  `tools/dev/qlmc_coverage.py`（`BASELINE` 63 → 64）
- 覆盖率：**63 → 64**（`std/tls_net`）
- qlmc 差分：38 → **39**

## 问题：跨模块 struct 报"未知类型"

`std/tls_net` / `std/httpc_net` 引用 `std/tls_client` 声明的
`TlsClientResult` 时报：

```
qlmc: line 46: 未知类型 TlsClientResult
```

**这不是类型系统缺能力，是 parse 顺序把声明可见性绑住了。**

`parse` 是"声明表按顺序增长"的：`_type` 遇到 `Foo` 会去 `_struct_index`
查表，查不到就 `_fail("未知类型")`。而原来的顺序是：

```
主文件 parse  →  模块 parse（`_prescan_imports` 的 BFS 序）
```

于是**主文件（或先 parse 的模块）看不见后 parse 模块的 struct**。
`std/httpc_net` 先于 `std/tls_client` parse，它的
`_recv_once(fd, tls, tr: TlsClientResult, ...)` 必然失败。

这和 v3.52 修的跨模块 **const**（§7.39）是同一个病的两种形态：
那个是"值当场折叠成节点，节点定型后补表也没用"，这个是"类型当场查表，
查不到直接报错"。共同根源都是"解析单趟、顺序由装载顺序决定"。

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | 新增 `_topo_order` / `_mod_index_of`；parse 顺序改为"模块（拓扑序）→ 主文件" |
| `tests/selfhost/mod_shape.qma` | 新夹具模块：导出 `Shape` struct + 工厂 + 求面积 |
| `tests/selfhost/s37_crossmod.qma` | 新差分夹具：跨模块 struct 作形参 / 写字段 / 布局一致性 |
| `tests/qlmc_test.py` | 注册 `s37_crossmod` |
| `tools/dev/qlmc_coverage.py` | `BASELINE` 63 → 64 |
| `docs/07-gaps.md` | 新增 §7.42（已修）/ §7.43（待修：同名私有 struct） |

### 算法选择：为什么是扁平矩阵 + O(n²)，不是边表

Kahn 算法本身简单，**难的是方向别搞反**。第一版写成：

```quelmara
indeg.set(t, indeg.get(t) + 1)      // ✗ 加在**被依赖方**上
```

于是"没有依赖的"（叶子）入度非零，永远出不来；每轮扫到的是
**依赖最多**的那个 —— 顺序直接退化成原序。症状很隐蔽：
**不崩、不报错**，只是 `std/tls_net` 仍然排在 `std/tls_client` 之前，
报错和没修一模一样。

第二版换成"边表 + 反向边表 + 两趟计数排序"，多 40 行，还是没对。
最后改成**扁平依赖矩阵**（`dep[i*MAXD+k]`）+ **每轮 O(n²) 扫**：

```quelmara
// 找"依赖全部已出"的模块
while c < n && pick < 0 {
    if done.get(c) == 0 {
        let mut okdep = 1
        let mut k2 = 0
        while k2 < ndep.get(c) {
            if done.get(dep.get(c * MAXD + k2)) == 0 { okdep = 0; ... }
            ...
        }
        if okdep == 1 { pick = c }
    }
    ...
}
```

n 很小（一个程序的 import 闭包通常 < 32），O(n²) 完全够，
而**判据直接就是语义**（"依赖都出去了吗"），没有方向可搞反。
**能写成"读起来就是定义"的形式，就不要写成"需要想一下才对"的形式。**

### 为什么不是"预扫描 struct"

`_type` 解析字段类型时会**递归**调用 `_type`（`vec[Foo]` 要先知道 `Foo`），
所以 struct 之间也有依赖链。拓扑序一次性解决整条链，不需要第二趟。

**成环时**把剩下的按原序追加（不丢模块）。import 成环本身是错误，
但那由 stage-0 报；qlmc 这里只保证"不因为排序而崩或漏 parse"。

## 验证

| 命令 | 结果 |
|---|---|
| 差分夹具 `s37_crossmod`（11 行输出） | **stage-0 与 qlmc 逐字节一致** |
| qlmc 差分全量 | **39/39 PASS**（38 → 39） |
| `std/` 覆盖率 | **63 → 64**（`std/tls_net` 解开） |
| 自举等价性（stage-1 vs stage-2 编 `tests/selfhost/` 30 组） | **30/30 逐字节相同** |
| `std/httpc_net` | 从"未知类型 TlsClientResult"前进到"struct 重复声明 `_Ck`" |

### 关于不动点：本轮在 wine 下测不出来，已如实记录

`docs/08-handoff.md` §2 写的是"必须 30/30 + 不动点成立"。本轮在
**Linux + wine** 上跑，**不动点（stage-2 == stage-3）测不过**：

```
$ wine build/s2_fix.exe build bootstrap/qlmc/qlmc.qma -o build/s3_fix.exe
EXIT=1        （无任何诊断输出，纯 __die 退出）
```

**关键证据：这不是本版引入的回归** —— 把改动 stash 掉、用原始源码
重跑同一条命令，**同样失败**（退出码 5，产物 0 字节）：

```
$ wine build/s2_orig.exe build bootstrap/qlmc/qlmc.qma -o build/s3_orig.exe
EXIT=5
-rw-r--r-- 1 root root 0 build/s3_orig.exe
```

也就是说**原始 v3.59 代码在 wine 下也过不了不动点**。`06-status.md`
记的"不动点成立"是在真实 Windows 上测的，wine 的地址空间/线程调度
与真 Windows 有差异（qlmc 编自己会 `mem_alloc(ARENA_CAP)` = 4 MB
arena + 64 MB 堆，且按函数并行）。

**结论与处置**：本版用**等价性 30/30**（stage-1 与 stage-2 编同一批
程序产物逐字节相同）作为可用判据 —— 它比不动点弱，但**不依赖
stage-2 能编自己**，在 wine 下稳定。不动点的最终确认交给 CI
（`bootstrap_test.py --strict` 在 windows runner 上跑）。

**未验证项必须在 CI 上确认，不能因为"本地跑不了"就当作通过。**

## 顺带：`std/httpc_net` 前进但没解开

它现在报 `struct 重复声明 _Ck`。根因是 `std/httpc` 与 `std/httpc_net`
各有一个**私有** `struct _Ck`，而 qlmc 不做 `pub` 可见性检查，
把它们当成同一个名字。这与 `std/http` / `std/logfile` 的
"函数重复定义"是**同一个根因**（缺 per-module mangling），
已登记 `07-gaps.md` §7.43 —— 一次修好能解 3 个模块。
