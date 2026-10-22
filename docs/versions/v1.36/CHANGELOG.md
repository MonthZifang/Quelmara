# v1.36 — 用户泛型：多类型参数 + 调用点推导（语言层黄标翻绿）

- 日期：2026-10-22
- 任务：语言层 P1-1（07-gaps §8 顺序：性能专项之后转语言层）。用户泛型 🟡 → ✅：
  多类型参数 + 调用点类型推导；显式实例化保留。红标（泛型 struct / 泛型方法 /
  类型约束）按协议先落 ❌ 行，后续轮次 红→黄→绿。
- 影响面：编译器（parser + expand_generics 重写）、标准库（新模块 std/gen）、
  测试（t81）、文档（02-language / 03-stdlib / 06-status / 07-gaps）

## 为什么是它

07-gaps §1 语言层第一张黄标表里，泛型是 P1-1（“让语言能撑住中型程序”的第一项）。
v1.11 只有单类型参数 + 显式实例化，每个调用点都要手写 `f[int](...)`——通用算法
（min/max/contains）写一次还要在调用点重复类型信息，推导是这条路上最大的摩擦。

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm.py` | `parse_fn` 支持 `[A, B, ...]` 多类型参数（重名报错）；调用点显式实例化支持多类型；普通调用泛型函数生成 `("gcall_infer", ...)` 节点；**`expand_generics` 重写**：多参单态化 + `_GenInfer` 推导引擎 |
| `tools/stage0/qlm.py` | 新增 `_ty_str` / `_ty_subst`（全容器形态类型替换）与 `_GenInfer`（函数内类型环境 + 一元化） |
| `std/gen.qma` | **新增**：泛型算法库（gen_min/max/clamp/dist/first/last/contains/index_of/reverse），纯 Quelmara，调用点推导单态化 |
| `tests/t81_generic_infer.qma` | **新增**：8 组覆盖（字面量/多参/显式/标注/structlit/调用返回/vec 一元化/嵌套/跨文件） |
| `tests/run_win_tests.py` | 注册 t81（主回归 143 → 144） |
| `tools/dev/gen_stdlib_doc.py` | DESC 补 `std/gen`，重新生成 `03-stdlib.md`（40→41 模块 / 452→461 公开函数） |
| `tools/stage0/qlm_cli.py` | VERSION 1.35.0 → **1.36.0** |
| `docs/02-language.md` | §4.5 泛型节重写（推导规则/边界）；陷阱 #9 改写 |
| `docs/07-gaps.md` | §1 用户泛型 🟡→✅；新增“泛型 struct/泛型方法”“类型约束”两条 ❌ |
| `docs/06-status.md` | 回归 142 → **144** |

## 实现要点

- **推导引擎 `_GenInfer`**：函数内轻量类型环境（形参 + let 标注 + 语句序推断、
  后写覆盖、流不敏感）+ 形参—实参一元化。推导来源：字面量（含 `fnum` 浮点）、
  结构体/枚举字面量、`vec[T].new`/`map[K]V.new`/数组字面量等构造节点、非泛型
  函数返回类型、泛型实例返回类型、vec/map/array 元素类型、结构体字段类型。
- **符号类型参数的环境传递**：泛型模板体的环境里变量类型可含本模板的类型参数
  （符号形态），实例化时经 `tp_map` 落地——嵌套泛型（模板里调模板）因此能逐层
  实例化，不需要全局类型推断器。
- **失败即报错**：推不出全部类型参数 → 编译期报错并提示显式实例化（带行号）；
  实参矛盾（`same(1, "s")`）→ 报 `int vs str` 冲突；显式个数不符 → 报需要 N 个
  得到 M 个。真实类型检查仍由 Lower 负责，推导只决定实例化目标。
- **顺手修掉一个 v1.11 埋的 bug**：`T { ... }` 占位字面量单态化结果此前是
  `("structlit", <字符串>, ...)`，下游按路径 list 消费——单字符结构体名（如 `P`）
  碰巧能跑，多字符名（`Point`）直接被按字符 join 成 `P.o.i.n.t` 报错。现改为
  路径列表，与解析器形态一致（t81 第 7 组回归）。

## 验证（本轮全部现跑）

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=144 FAIL=0 SKIP=1**（v1.35 为 143；SKIP 为 WSL 交叉验证，沙箱拦） |
| `python tools/stage0/qlm_cli.py run tests/t81_generic_infer.qma --target win` | ok（8 组全过，含跨文件 `import std.gen` 隐式调用） |
| `python tools/stage0/qlm_cli.py run tests/t56_generic.qma --target win` | ok（v1.11 显式实例化零破坏） |
| `python tools/dev/check_names.py` / `check_origin.py` / `check_docs.py` | 三禁 PASS（含数字单一来源、版本号同源） |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS：41 模块 / 461 公开函数 |
| 性能（`bench/p0_bench.qma`、`gbench.qma`、`bench_str.qma`，min-of-N） | 与改动前基线同水平：sha256 42ms（基线 41）、mix_arith 47.5ms（48.2）、branchy 39.5ms（42.2）、loopsum50m 76.5ms（76.7）、collatz 101.9ms（104.0）——全部在 VBS 噪声带内，**无回退** |
| 编译期错误路径（CLI 手工） | 推不出/冲突/个数不符三种报错信息均带行号与修复提示 |

## 已知边界 / 遗留

- **推导是流不敏感、尽力而为**：分支里改绑类型可能推错；推不出就要求显式
  实例化或加标注。真正的类型检查在 Lower。
- **类型实参只接受具名类型**（标量/struct/enum）：`f[vec[int]](...)` 不做
  （容器形态的实参语法未开）。
- **无约束声明**：“T 须支持 `<`/`==`”是文档性的——违反它在 Lower 报类型错，
  不是静默错（std/gen 头部已写明）。
- **泛型 struct / 泛型方法仍 ❌**：按协议下一轮进入 红→黄。
- **跨文件前向泛型**（被调用方在调用方之后才解析）仍须显式方括号——
  解析期还不知道被调用方是泛型。
- 单态化实例名 `f__T1_T2` 与非泛型函数重名会报错（原有纪律，未变）。
