# v1.56 — 切片别名写入截断（整数宽度行翻绿）

- 日期：2026-10-23
- 任务：07-gaps §1「整数宽度」行最后一项**语义**缺口——`slice_of(a)` 之后
  `s[i] = 300` 不按元素宽度截断（切片元素标签只跟踪 `str`）。本版把标签带全并在
  写点截断，该行按语义口径翻绿；行内另一项「`vec[u8]` 槽仍 8 字节」经核实是
  **内存打包**（语义早已正确），移到 §5 性能专项单开一版。
- 影响面：`tools/stage0/qlm_native.py`（`arr_elem` 记元素名 + 切片元素标签三处来源 +
  `lower_assign_index` 截断）、`tests/t94_slice_narrow.qma`（新增）、
  `tests/run_win_tests.py`（注册）、`docs/02-language.md`（§8.1）、
  `docs/07-gaps.md`（§1 行 / §5 / §8）、`docs/06-status.md`、
  `tools/stage0/qlm_cli.py`（VERSION）

## 为什么是它

切片是**零拷贝别名**：写 `s[i]` 落到底层数组。数组声明是 `[4]u8`，但写入按 64 位
存，读回就是 300 而不是 44——二进制格式、协议头、哈希输入全会被写脏，而且**不报错**。
v1.40 把窄值截断铺到了 let / 形参 / 返回值 / struct 字段 / enum 载荷 / vec 元素 /
定长数组，唯独别名路径漏了，因为切片元素类型当时只用来区分 `str`（打印要不要当指针）。

这条比"再做一个新特性"重要：它是**已有语义的漏洞**，踩到就是静默写错数据。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm_native.py` | ① `arr_elem`（原来只给 f64 数组记 `"f64"`）扩成窄数组也记元素类型名；② 切片元素标签三处来源都带全：`slice_of(数组)`、`[]T` 形参、`fn() -> []T` 返回值，子切片与 `let` 绑定继承（原有 `_slice_elem` 透传链）；③ `lower_assign_index`：`s[i] =` 与 `s[i] +=` 两条路径都按元素宽度 `trunc`（int 切片 `nb=None`，零成本） |
| `tests/t94_slice_narrow.qma` | **新增**：16 条断言——u8 别名写 / 复合赋值 / i8 有符号回卷 / `[]u8`·`[]i8` 形参 / 子切片继承 / 返回值继承 / int 切片不受影响 / u16 回卷 |
| `docs/02-language.md` | §8.1 表格加「切片别名写入」一行；删掉"切片别名写入暂不截断"的旧边界 |
| `docs/07-gaps.md` | §1 整数宽度行 🟡→✅；§5 新增「vec 窄元素槽压缩」专项（内存打包，单开一版）；§8 路线图打勾 |

## 实现要点

- **标签必须跟数据走**：切片值只有 `{ptr,len}` 两个字，元素类型是**编译期**属性，
  靠 vreg 上的旁路表 `slice_elem` 记。三处来源漏一处就等于漏一条写入路径：
  `slice_of` 漏了子切片断，形参漏了被调方断，返回值漏了跨函数断。
- **只影响窄元素**：`int`/`str` 切片的 `nb` 仍是 `None`，写点不发射 `trunc`——
  这也是 bench 产物逐字节不变的原因。
- **不引入新 IR**：截断复用 v1.40 的 `trunc` 指令，A64/C 后端零改动。

## 验证（本轮全部现跑）

<!-- verify:begin -->
| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=163 FAIL=0 SKIP=1**（SKIP 为 WSL 交叉验证） |
| `python tests/lexdiff.py` | **PASS=149 FAIL=0** |
| `python tests/parsediff.py` | **PASS=127 FAIL=0** |
| `python tests/bodydiff.py` | 一致 1292 / 分叉 1182 / SKIP 同步 25 / SKIP 不同步 35（诊断项） |
| `python tests/irdiff.py` | **PASS=70 FAIL=0 SKIP=53** |
| `python tests/emitdiff.py` | **PASS=10 FAIL=0** |
| 三道门禁 | check_names / check_origin / check_docs 全 PASS |
| **性能（双向对照）** | `git worktree add ../perfbase-v156 a388dc9` 建基线，两树各构建 8 个 bench：**`.qex` 逐字节相同**（p0/gbench/bench_str/find/simd/sync/gzip/bench_mod）——`int`/`str` 切片不带窄标签，写点不发射 `trunc`，非窄代码零指令变化 |

> 口径：HEAD `dc248e9`（v1.55 标准库轨）+ 本版改动。

## 已知边界 / 遗留

- **`vec[u8]` 槽仍 8 字节**：语义正确（push/set 已截断），只是内存不压缩。压缩要把
  运行时从 `ln*ew*8` 字寻址改成字节寻址 + 有符号扩展加载，push/get/set/pop/foreach/
  grow 全套 + A64 同步，已登记 §5 性能专项，单开一版做。
- 切片元素标签是 **lowering 期**信息：跨 `callr` 间接调用（无签名）时目标拿不到标签，
  经函数值写入窄切片不截断（与"callr 无签名"同一类已知边界）。
- 标签只对具名标量元素生效；`[]vec[int]` 这类容器元素不涉及窄宽度。
