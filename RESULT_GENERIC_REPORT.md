# result[T,E] 受控单态化 —— 实现简报

日期：2026-10-19
改动范围：`tools/stage0/qlm.py`（前端 + C 后端共用前端部分）、`tests/t20_result_generic.qma`（新增）、
`tests/run_native_tests.sh`、`tests/run_win_tests.py`。
**未触碰**：`tools/stage0/qlm_native.py`、`tools/stage0/qlm_opt.py`、`tools/stage0/qlm_pe.py`（后端零改动）。

## 一、实现思路（完全照抄 `option[T]` v0.8 先例）

核心思想：**前端单态化 + 合成真枚举**。`result[T,E]` 不进任何后端——在解析期按 `(T,E)`
类型元组合成一个真枚举 `__res_<T>_<E>`，类型元组坍缩为 `("named", "__res_<T>_<E>")`，
下游 enum 布局 / match / 聚合返回 ABI / `?` 降级全部复用既有通路。

### 改动点（全部在 `tools/stage0/qlm.py`）

1. **词法**：`KEYWORDS` 加入 `"result"`（与 `option`/`chan` 同级的关键字类型名）。
   全库 grep 确认没有任何 `.qma` 源码把 `result` 当标识符用，无兼容性影响。

2. **`Parser.parse_type`**：新增 `result` 分支——`result[T, E]` 解析两个类型实参
   （T=Ok 载荷，E=Err 载荷），调用 `ensure_result_enum`，返回 `("named", name)`。

3. **`Parser.ensure_result_enum(tt, et, line)`**（新增，紧挨 `ensure_option_enum`）：
   - 校验 T、E 各自必须是 `int/i64/i32/i16/i8/u64/u32/u16/u8/bool/str` 标量，
     超出范围抛 `SyntaxError(f"line {line}: result[T,E] 的 T/E 暂只支持整数/bool/str 标量")`；
   - 合成枚举名 `"__res_" + T名 + "_" + E名`（如 `result[int,str] → __res_int_str`）；
   - 变体按 **`Ok(value: T)` / `Err(error: E)` 顺序**声明（Ok 固定在前），登记进
     `self.enums` 并追加 `decl_order`（保证 C 端 typedef 按声明顺序输出）；
   - 幂等：同名合成枚举只登记一次，多次出现共享。

4. **`Parser.parse_primary`**：新增 `result` 构造脱糖分支（与 option 分支同构）：
   `result[T,E].ok(x)` → `("enumlit", ["__res_<T>_<E>", "Ok"], [("value", x)])`，
   `result[T,E].err(e)` → `("enumlit", [...], [("error", e)])`；
   其它方法名（如 `.some(...)`）明确报错。

5. **`resolve_option_patterns(arms, scrut_ename)`**（改写，函数名保持不变，
   自研 native 后端按此名 import）：模式路径首段改写从只认 `Option` 扩展为——
   求值式是 `__opt_*` 时把 `Option.*` 首段改写为该合成枚举名；
   求值式是 `__res_*` 时把 `Result.*` 首段改写为该合成枚举名；
   其余（含用户手写的 `Result`/`ReversedResult` 真枚举）原样返回。
   该函数被 C 后端 `gen_match` 与自研 native 的 match 降级共用，一处改动两链生效。

### `?` 传播（零改动，直接复用）

既有 `?` 降级（C 端 `gen_expr` 的 `try` 分支、native 端 `eval` 的 `try` 分支）本来就按
**声明顺序**查 `Ok`/`Err` 索引（`next(i for i,(vn,_) in ... if vn == "Ok")`），不硬编码 Ok=0
（`tests/t17_result.qma` 里 `ReversedResult` 是 Err 在前的，靠这一点通过）。合成的
`__res_*` 是标准 `Ok/Err` 双单载荷变体枚举，直接落进该通路，两链零改动。

### 必须的校验（均已生效，见下文实测）

- `?` 的传播目标所在函数返回类型必须是同一个合成枚举：复用既有检查
  （C 端 `? 所在函数必须返回相同的结果枚举`，native 端同文案、比较 `fn_ret_agg`）。
- `result[T,E]` 元素类型超范围、构造方法名非法：`ensure_result_enum` / `parse_primary`
  报错，**不静默错编**。

## 二、边界条件与报错行为（实测）

用一次性探针文件验证（native / C 两链报错一致，均为中文 + `line N:` 格式）：

| 场景 | 报错 |
|---|---|
| `result[int, [4]int]`（E 非标量） | `SyntaxError: line 2: result[T,E] 的 T/E 暂只支持整数/bool/str 标量` |
| `result[T,E]` 结果上 `?` 用在返回 `int` 的函数里 | `SyntaxError: ? 所在函数必须返回相同的结果枚举` |
| `result[int, str].some(1)` | `SyntaxError: line 3: result[T,E].some 用法无效（仅 ok(x)/err(e)）` |

其它边界：
- match 模式 `Result.Ok(v)`/`Result.Err(e)` 只在求值式确为 `__res_*` 时改写；
  用户手写 `enum Result {...}`（t17）完全不受影响（求值式名不带 `__res_` 前缀，原样匹配）。
- 合成枚举按 `(T,E)` 去重：同一程序里多处 `result[int,str]` 共享一个 `__res_int_str`，
  不同组合（`__res_int_str` / `__res_str_int` / `__res_bool_bool`）各自独立，布局互不干扰。
- `?` 的 Ok 载荷限制（整数/bool/str 标量）是既有检查，合成枚举的 T 天然满足。

## 三、三条测试链实测结果（原样）

```
$ bash tests/run_native_tests.sh
[14] result[T,E] 单态化 + ? 传播 + match 解构
  ✅ native result[T,E] 构造/?/match 正确
  ✅ C result[T,E] 构造/?/match 正确
  ✅ result[T,E] 自研后端 == C 后端
----------------------------------------
PASS=57 FAIL=0
```

```
$ bash tests/run_tests.sh
----------------------------------------
PASS=16 FAIL=0
```

```
$ bash tests/test_corelib.sh
结果: PASS=34 FAIL=0 SKIP=0
```

```
$ python3 tools/stage0/qlm_native.py run tests/t20_result_generic.qma
result generic ok

$ python3 tools/stage0/qlm.py run tests/t20_result_generic.qma
[qlm] tests/t20_result_generic.qma -> build/t20_result_generic.c
[qlm] config: .../Quelmara.toml | multicore=True threads=auto
[qlm] cc: cc -std=gnu11 -O2 -pthread -o build/t20_result_generic build/t20_result_generic.c
[qlm] exec build/t20_result_generic
result generic ok
```

两条链的**程序输出完全一致**（`result generic ok`）。C 链 stdout 多出的 `[qlm]`
横幅是编译器日志（所有既有测试同样如此，各测试段统一用 `grep -v '^\[qlm'` 过滤）；
`run_native_tests.sh` [14] 段里的 diff 检查即按此约定过滤后逐字节比对，通过。

native 计数说明：基线 54 项 → 本次新增段 [14] 3 项 → 57 项，FAIL=0。
C 后端 16 项、corelib 34 项均为原样保持。

## 四、新增测试 tests/t20_result_generic.qma 覆盖点

- `result[int,str]`：`.ok(x)`/`.err(e)` 构造、函数返回（聚合 ABI）、
  `Result.Ok(v)`/`Result.Err(e)` match 解构（Ok/Err 两分支）；
- `?` 传播：正常分支（`add_one(41)`）+ 错误分支（`add_one(-1)`，Err 原样返回）；
- `result[str,int]`（T/E 对调）：构造、`?` 正常分支 + 错误分支、解构；
- `result[bool,bool]`：bool 载荷构造/解构、`?` 正常分支 + 错误分支。
测试自校验（assert），末行 `print("result generic ok")` 供双链 diff。

登记位置：
- `tests/run_native_tests.sh` 新增 `[14]` 段（顺延 [13]，含 native/C 双跑 + 双链 diff 共 3 个断言）；
- `tests/run_win_tests.py`：`case_selfcheck("result_generic", "tests/t20_result_generic.qma")`
  （与 t17/t19 同级登记），并加入 PE×ELF 交叉验证用例表（与 t19 同表）。
  该脚本为 Windows 专用（非 Windows 下执行级用例自动 SKIP），本机已做 `py_compile` 语法验证。

## 五、已知限制

1. **元素类型范围**：T、E 仅支持整数/bool/str 标量（与 `option[T]` 现状一致）；
   结构体、枚举、数组载荷明确报错，不支持。
2. **构造语法只走 `result[T,E].ok/err` 脱糖**：表达式里不支持 `Result.Ok(x)` 形式的
   构造（那是用户手写 Result 的写法；合成枚举的构造入口是 `result[T,E].ok(x)`）。
   match 解构侧 `Result.Ok/Err` 支持（模式路径改写）。
3. `?` 用于语句位（`f()?;` 裸语句）仍走既有整型错误码通路，对聚合结果不适用
   （改动前对用户 Result 亦然，未扩权）。
4. `?` 返回类型不匹配的报错（`? 所在函数必须返回相同的结果枚举`）沿用既有文案，
   不带行号（与 t17 用户 Result 的既有行为一致）。
5. 合成枚举名 `__res_<T>_<E>` / `__opt_<T>` 为保留前缀，用户不应声明同名枚举
   （既有 `option` 同样约定）。
6. Windows PE 链（`run_win_tests.py`）无法在本机执行级验证，仅做了语法编译检查；
   由于改动全在前端且合成枚举走通用枚举通路（t19 先例已在该表中全绿），风险低。

## 附：过程记录（诚实起见）

- 动手前基线复测：`run_native_tests.sh` 第一轮出现过一次 **PASS=53 FAIL=1**（当时未留全量日志，
  未能定位具体项）；紧接着复跑两轮均 **PASS=54 FAIL=0**。该套件存在与本次改动无关的
  偶发抖动（疑似 parfor/spawn/chan 的超时类断言）。改动后复测一轮 **PASS=57 FAIL=0**。
- `tests/run_tests.sh` PASS=16 FAIL=0、`tests/test_corelib.sh` PASS=34 FAIL=0，改动前后一致。
