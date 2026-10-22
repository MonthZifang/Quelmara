# v1.41 — map 值扩容：map[K]Struct / map[K]Enum（语言层黄标翻绿）

- 日期：2026-10-23
- 任务：语言层 §1 `map[K]V` 🟡 → ✅：V 从标量扩到具名 struct/enum——
  配置表/符号表不再拆平行 map。
- 影响面：parser（map 值类型校验放开）、运行时（值槽 N 字化 + _n 两个新函数
  + grow 加宽）、C 后端（esz + set_n/get_n）、测试（t86）、文档

## 为什么是它

v1.39 收尾时标注"剩余项里最大"的一项。v1.37（vec[map]）与 v1.39（struct
嵌套聚合）已把"句柄 1 槽 / 多字视图"两类机制铺好，map 值的缺口是**值槽
硬编码 1 字**：`__map_open` 按.cap*8 分配值表、`__map_set/get` 单字读写。
聚合值按 agg 布局占 N 字——与 vec[Struct]（`__vec_get_n/set_n`，esz 字
元素）完全同构，照搬即可，零新机制。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm.py` | `map_kv_tag`：值侧放行具名聚合（返回类型名；键仍限标量；`byte` 显式拒绝） |
| `tools/stage0/qlm.py` | C 运行时：`QlmMap` 加 `esz` 字段；`qlm_map_open(cap, ktag, esz)`；`qlm_map_grow` 值拷贝改 `memcpy` esz 字；新增 `qlm_map_set_n` / `qlm_map_get_n`（探测结构与标量版逐行同构） |
| `tools/stage0/qlm.py` | C 代码生成：mapnew 传 `sizeof(V)`；`gen_map_method` 聚合值走 set_n/get_n（语句表达式物化 `_vt`，与 vec[Struct] 同模式）；`check_map_arg` 聚合值精确同名校验；`Infer` 的 map get 返回 `struct:/enum:` 类型串 |
| `tools/stage0/qlm_native.py` | mapnew：`vw = agg_size(V)`（未声明聚合在此 fail-fast），`__map_open` 加第三参 |
| `tools/stage0/qlm_native.py` | `__map_open`：控制块 56→64 字节，槽宽存 `[7]`，值表容量 ×vw（**标量 vw=1 布局逐字节不变**） |
| `tools/stage0/qlm_native.py` | 新增 `__map_set_n` / `__map_get_n`：按控制块槽宽逐字拷入/拷出；`__map_grow` 值搬运按槽宽逐字（运行时循环） |
| `tools/stage0/qlm_native.py` | `lower_map_method`：聚合值 set 实参须同名 struct/enum 值（`_struct_of` 精确校验），get 开新帧槽拷出并挂聚合标记——let/传参/取字段全部按既有 struct 值语义走 |
| `tests/t86_mapstruct.qma` | **新增**：6 组覆盖（存取/覆盖写/拷出即副本、40 条逼出两次 rehash、del 墓碑+复用、句柄字段共享、枚举值+match、标量与聚合 map 共存） |
| `tests/run_win_tests.py` | 注册 t86（主回归 148 → 149） |
| `tools/stage0/qlm_cli.py` | VERSION 1.40.0 → **1.41.0** |
| `docs/02-language.md` | 类型表 map 行更新；陷阱 #10 改为"按值存储"语义说明 |
| `docs/07-gaps.md` | §1 `map[K]V` 🟡→✅（键限标量、复合容器作值不做，如实登记）；§8 推进顺序同步 |
| `docs/06-status.md` | 回归 149 / lexdiff 134 / parsediff 118 / irdiff SKIP 48 |

## 实现要点

- **标量热路径零改动**：`__map_hash` / `__map_find` / `__map_key_eq` /
  `__map_set` / `__map_get` / `__map_has` / `__map_del` 一行未动；聚合值走
  新增的 `_n` 变体（只在聚合值 map 上发射）。`__map_open` 加参但 vw=1 时
  布局与 v0.10 逐字节一致；`__map_grow` 的值搬运改运行时逐字循环（扩容是
  均摊路径，不在热区）。
- **值槽宽是运行时事实**：同一程序可共存 `map[str]int` 与 `map[str]Point`，
  槽宽存在控制块 `[7]`，`_n` 函数按它分派——编译期不发错宽度的调用。
- **拷贝语义与 struct 一致**：`set` 把实参帧槽的 N 字拷进表槽（按值）；
  `get` 拷出到新帧槽并挂 struct 标记——改副本不影响表内（t86 §1 断言）。
  struct 里的 vec/map/chan 字段是句柄，随值拷贝、底层共享（v1.39 语义顺延，
  t86 §4 断言）。
- **fail-fast 纪律**：未声明的聚合值类型在 mapnew 处报"未声明的结构体/枚举"；
  set 实参类型不匹配编译期拒绝；键不存在 get 依旧 fail-fast 退出。

## 验证（本轮全部现跑）

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=149 FAIL=0 SKIP=1**（v1.40 为 148；SKIP 为 WSL，沙箱拦） |
| `python tools/stage0/qlm_cli.py run tests/t86_mapstruct.qma --target win` | ok（6 组全过，含 40 条 rehash 后逐键取回） |
| `python tools/stage0/qlm_cli.py build tests/t86_mapstruct.qma --target c` | C 源码生成全过（17 处 `qlm_map_set_n/get_n` 调用点；gcc 本机无，执行归 CI） |
| `python tools/dev/check_names.py` / `check_origin.py` / `check_docs.py` | 三禁 PASS |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS：41 模块 / 461 公开函数 |
| `python tests/lexdiff.py` / `parsediff.py` | 134 / 118 全绿 |
| `python tests/bodydiff.py` | 一致 1172 / 分叉 872 / SKIP 24-18（无新增 MISMATCH；t86 main 超出 stage-1 Phase 1 覆盖，不入 corpus） |
| `python tests/irdiff.py` / `emitdiff.py` | 66-0-48 / 10-0 |
| 性能（改动前 = git worktree@HEAD(v1.40) 基线） | 见下——**无回退** |

性能对照（基线 → 改动后；VBS 噪声带 ±50%）：

| 项 | 基线 | 改动后 |
|---|---|---|
| sha256 / split+join / url / json | 41 / 9 / 74 / 2 ms | 41 / 9 / 75 / 2 ms |
| gbench tokenizer / mix_arith / map_str / branchy | 3.77 / 47.7 / 5.15 / 39.7 ms | 3.83 / 47.8 / 4.16 / 39.5 ms |
| gbench str_build / buf_scan / nested / hashmix | 0.80 / 1.77 / 0.40 / 50.0 ms | 0.79 / 1.99 / 0.40 / 52.8 ms |
| bench_str scan16k / concat20k / loopsum50m / collatz | 224 µs / 77.0 / 76.9 / 101.7 ms | 234 µs / 76.1 / 76.9 / 102.5 ms |

全部在噪声带内。改动未触碰标量 map 的任何热路径函数——map_str（10k 次
字符串键操作）双向都在 4-5 ms 历史波动带内，与"热路径零改动"一致。

## 已知边界 / 遗留

- **键仍限 int/bool/str 标量**：struct 键需要结构化相等+哈希（编译期合成
  hash/eq），红标"泛型 struct"落地后一并考虑。
- **复合容器作值不做**：`map[str]vec[int]` 需要 mapinner 标签链进 map 值
  标签（与 vec[map] 同构，机制现成），按需再做——句柄值 1 字、拷贝共享
  底层，语义要先写清（clear/扩容不释放）。
- **AArch64 未接 map**（既有边界，t86 在 irdiff SKIP=48 内如实登记）。
