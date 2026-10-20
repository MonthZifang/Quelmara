# Rosoto 交接文档（HANDOVER）

> 工作区状态（2026-10-20 晚间）：**v0.8 已提交 `d61c593`**；v0.9 性能轮 + v0.10 map/浮点在工作区待提交。
> v0.9：`opt_modsum` 模和折叠 + 范围分析扩展 + `mul_const` 回退路径错编修复（loop_sum 11–13ms，见 CHANGELOG）。
> v0.10：`map[K]V` 开放寻址哈希表（t22）+ 浮点实际运算（t23，修复 `__f64_to_str` 科学计数法死循环）。
> 本机（Windows）验证：PE 链 [1]–[6] 52 项全绿；[7] 交叉验证与 native/C 链需 Linux/WSL 环境。
> 代码总量：`tools/` 12.3k 行 Python + `tests/` 1.5k 行
>
> ### v0.10 一句话
> `map[K]V`（K/V ∈ int/bool/str，开放寻址 + 线性探测 + 墓碑 + 扩容）与浮点实际运算
> （f64/f32 四则/比较/转换/格式化，定点 + 科学计数双路径）三链打通；
> 顺带修复自研后端 `__f64_to_str` 在科学计数路径的非 SSA 死循环（`print(1e-7)` 挂死）。

---

## 0. 一句话结论

Rosoto 现在可以在三条链上使用用户定义的 Result 枚举和 `?`：

```rosoto
enum Result {
    Ok(value: int)
    Err(error: str)
}

fn parse(n: int) -> Result {
    if n < 0 { return Result.Err("negative") }
    return Result.Ok(n)
}

fn add_one(n: int) -> Result {
    let value = parse(n)?
    return Result.Ok(value + 1)
}
```

错误分支复制当前 Result 并直接返回，成功分支提取 `Ok` 载荷。`Ok`/`Err` 可按声明顺序排列，
不再假定 `Ok` 必须是 tag 0。

同时推进了 native 优化器：严格递增、常量上界循环可进行非负范围传播，安全地消除有符号魔数除法的
符号修正链；parfor/spawn 独立 worker 保留为寄存器分配边界，避免内联造成 spill 回退。

---

## 1. 这一轮做了什么

### 1.1 Result + `?`

| 后端 | 实现 |
|---|---|
| Linux 自研 x86_64 | Result 作为已有 enum 聚合值，`?` 检查 tag；Err 整体拷贝到隐藏返回槽后 return；Ok 载荷从槽 1 读取 |
| Windows PE | 复用同一 RosIR/Lower，PE 发射层无额外分叉 |
| C 后端 | GNU C statement expression：Err 直接 `return`，Ok 返回 `u.Ok.value` |

当前明确边界：

- Result 必须是**用户定义 enum**，且恰有两个单载荷变体 `Ok(value)` / `Err(error)`；
- `Ok` 载荷仅支持标量 int/bool/str；
- 泛型 `result[T,E]` 尚未自动单态化；
- 结构体/多槽 payload 暂不接受，避免只读取一个槽导致静默错编；
- `?` 所在函数必须返回相同的 Result enum。

`t17_result.ros` 覆盖：正常传播、错误传播、`Err` 在 `Ok` 前声明的反向 tag 顺序，
Linux native / Windows PE / C 三链均通过。

### 1.2 自研优化器

#### 非负范围传播

`analyze_nonneg()` 现在只接受有明确证明的值：

- 单次常量定义；
- 严格递增的 `i < hi` 循环；
- `lo`、`hi` 是可追溯常量；
- 步长为正且末次步进不会溢出；
- 循环体不重定义归纳变量。

之后才传播 `add/mul/shl/sar/umulhi` 的上界，用于安全消除有符号魔数除法的符号修正。
证明不满足时保守保留原代码。

#### worker 内联边界

parfor/spawn worker 的独立栈和寄存器压力敏感，继续保留 `Fn.no_inline` 边界；
避免把 helper 塞进 worker 后扩大活跃区间、触发 spill，导致热循环反而变慢。

> 本轮没有把未验证的周期归约重写保留在最终管线；当前性能提交只包含已通过全量回归的范围证明与 worker 边界。

### 1.3 产品后端策略

- `rosoto_cli.py` 默认目标：Windows 使用 `win`，其他平台使用 `native`；
- C 后端必须显式 `--target c`，只用于交叉验证、自举、移植和测试；
- 文档已同步：README / SPEC / BACKEND 都标明 C 后端不是产品默认运行路径。

### 1.4 回归

新增：

- `tests/t17_result.ros`；
- `tests/t19_option.ros`（v0.8）；
- native 回归 [12]：Result native + C 传播；[13]：option native + C；
- Windows 回归：Result / option PE 自校验 + PE×ELF 交叉验证。

当前总量：

```
Windows PE 57 ✅  |  自研 Linux 54 ✅  |  C 16 ✅  |  corelib 34 ✅  |  io_uring 26 ✅
总计 187 项（v0.7 的 183 + v0.8 option 4 项）
```

---

## 2. 还没有做什么

### 2.1 语言特性

| 特性 | 状态 | 优先级 |
|---|---|---|
| `option[T]` 单态化 | ✅ v0.8 合成枚举 + match 解构（int/bool/str） | — |
| 泛型 `result[T,E]` | ❌ 尚未自动展开 | 高 |
| `[]T` 切片（指针+长度） | ❌ 只有类型语法，数组不能作参数 | 高 |
| `map[K]V` | ❌ 未实现 | 高 |
| 数组作函数参数/返回值 | ❌ `[N]T` v0.6 边界明确报错 | 高 |
| `chan.close()` / `select` / 无界通道 | ❌ | 中 |
| `h.join()` 方法式语法 | ❌ 当前是 `join(h)` | 中 |
| 泛型 / interface | ❌ | 中 |
| 所有权 + 借用检查 | ❌ arena/spawn/array 依赖约定 | 中 |
| `@simd` / `@no_preempt` / `@rc[T]` / `@extern("C")` | ❌ | 中 |
| 浮点实际运算 | ✅ v0.10 运算/比较/转换/格式化三链打通（t23，f64+f32） | — |
| `rosoto_fmt` 新语法覆盖 | ❌ | 低 |

### 2.2 平台 / 性能

| 项 | 状态 |
|---|---|
| Windows IOCP/AFD | ❌ `net.TcpServer` 尚未进入 Windows PE 后端 |
| 自研 Linux epoll 网络 | ❌ native 后端尚无网络 intrinsic |
| macOS/iOS Mach-O + kqueue | ❌ 需 Mac 真机/CI |
| Android / wasm64 | ❌ |
| AArch64 spawn/chan | ❌ 需要 `ldaxr/stxr` 原子发射层 |
| SIMD 自动向量化 | ❌ loop_sum 与 gcc -O2 的主要差距 |
| 尾调用消除 / LTO / 热重载 | ❌ |
| Windows PE 调试信息 / SEH unwind | ❌ |

### 2.3 工程化

| 项 | 状态 |
|---|---|
| `rosoto test --target all` | ❌ 需分别指定 |
| 跨平台 bench 基线 | 🟡 有命令，没有稳定 baseline 文件 |
| Linux/Windows CI | ❌ 未接 |
| Windows C 后端执行验证 | ❌ 本机无 gcc/clang |

---

## 3. 差什么

1. **git remote**：本地仓库仍没有远端 URL，因此不能完成网络 push。
2. **Mac/ARM64 机器或 CI**：macOS Mach-O/kqueue 与 AArch64 真机验证缺硬件。
3. **Windows C 工具链**：C 回归继续依赖 WSL gcc。
4. **IOCP 压测环境**：需要 Windows 句柄上限、防火墙配置和压测客户端。
5. **SIMD 基线环境**：需要固定 CPU、固定构建参数和 baseline 文件，避免把机器负载误判成优化收益。

---

## 4. 写了多少

| 类别 | 文件 | 说明 |
|---|---|---|
| 前端 + C 后端 | `tools/rosoto.py` | 2230 | Result `?` C 降级、tag 顺序/标量边界检查 |
| 自研 x86_64 | `tools/rosoto_native.py` | 3095 | Result `?` native 降级、tag 顺序处理 |
| RosIR 优化器 | `tools/rosoto_opt.py` | 1002 | 范围传播、worker 内联边界、保守溢出条件 |
| Windows PE | `tools/rosoto_pe.py` | 353 | 未改（复用 RosIR） |
| 命令行 | `tools/rosoto_cli.py` | 319 | 版本 0.7.0、主机架构默认 target |
| 测试 | `tests/run_win_tests.py` | 363 | Result Windows PE 回归 |
| 测试夹具 | `tests/t17_result.ros` | 61 | 正常/错误/反向 tag 顺序 |
| 文档 | `README.md` / `SPEC.md` / `BACKEND.md` / `HANDOVER.md` | — | v0.7 同步 |

**测试规模**：183 项全绿（Windows 55 / native 52 / C 16 / corelib 34 / io_uring 26）。

---

## 5. 需要写什么

1. **`[]T` 切片**：`{ptr,len}` 两字表示；数组到 slice 的零拷贝转换；slice 参数/返回值；
   这是 native `[]byte` 网络回调的前置。
2. **泛型 `option[T]` / `result[T,E]`**：在当前用户定义 Result 基础上做受控单态化。
3. **`map[K]V`**：开放寻址 + arena 绑定，先支持标量键值。
4. **native epoll / Windows IOCP 网络**：需要 slice 与间接回调调用。
5. **SIMD 自动向量化**：先做 canonical reduction loop，再加 `@simd`。
6. **macOS Mach-O + kqueue**：有 Mac runner 后落地。

---

## 6. 怎么接着干

```bash
# 全量回归（183 项）
bash tests/run_native_tests.sh      # 52
bash tests/run_tests.sh             # 16
bash tests/test_corelib.sh          # 34
bash tests/test_uring.sh            # 26
python tests/run_win_tests.py       # 55

# Result 三链
python tools/rosoto_pe.py run tests/t17_result.ros
python3 tools/rosoto_native.py run tests/t17_result.ros
python3 tools/rosoto.py run tests/t17_result.ros

# 性能审计
python tools/rosoto_cli.py bench examples/loop_sum.ros --target win --runs 5
python tools/rosoto_native.py build examples/loop_sum.ros -o build/loop

# 调试/IR
python tools/rosoto_pe.py build tests/t17_result.ros -o build/x.exe --dump-ir --no-opt
```

### 新增 IR/优化改动检查表

1. `vreg_mentions`
2. `_subst_vregs`
3. `_map_ins`
4. `PURE`
5. `_EFF`
6. `_LAT` / `_TERM`
7. `allocate.call_sites`
8. x86/Windows `gen_instr`
9. AArch64 `gen_instr`（若跨架构）

### 累计教训

- Result 的 `Ok` tag 不能硬编码为 0，必须按 enum 声明顺序查索引。
- Result `?` 目前只接受两个单载荷变体和标量 Ok payload，超出边界必须报错。
- 非负范围证明必须检查唯一初始化、唯一步进定义、上界和溢出；不能跨控制流读取旧常量。
- worker 是独立栈/寄存器压力边界，不能盲目内联。
- 内联标签必须带 caller 名字，否则跨函数同名会把跳转导入错误函数。
- C helper 只能引用 helper 形参，不能引用调用点局部变量名。

---

## 7. 版本控制 / 远端

- **git remote 已配置并推送**：`origin = https://github.com/MonthZifang/Rosoto`（2026-10-20）。
- 最新提交：
  - `cd6468e` archive: v0.2 快照（rosoto_old_v02.tar.gz）
  - `b42e0a4` v0.9+v0.10：modsum 折叠 + 泛型 result/切片 + map[K]V + 浮点
  - `d61c593` v0.8 option[T]
  - `d38c359` v0.7 Result `?`
  - `ff8f830` v0.6 arrays
  - `3e9b8c0` v0.5 chan
- 后续推送：`git push origin master`。
- 工作区已整理为单一文件夹：`Rosoto/rosoto/`（git 仓库）；历史快照
  rosoto_map / rosoto_rg / rosoto_old_v02 与顶层 scratch 已清出工作区
  （old_v02 内容以 `rosoto/archive/rosoto_old_v02.tar.gz` 形式保留在仓库内）。

---

## 8. 文件清单

```
修改：
  tools/rosoto.py          C Result ? 生成、Result 类型检查
  tools/rosoto_native.py   native Result ?、tag 顺序与标量边界
  tools/rosoto_opt.py      非负范围传播、worker 内联边界
  tools/rosoto_cli.py      产品默认 target、版本 0.7.0
  tests/run_native_tests.sh / tests/run_win_tests.py
  README.md / SPEC.md / BACKEND.md / HANDOVER.md

新增：
  tests/t17_result.ros     Result Ok/Err、错误传播、反向 tag 顺序

v0.8 本轮改动（option[T]）：
修改：
  tools/rosoto.py          KEYWORDS+option、ensure_option_enum 单态化、parse_type/parse_primary 构造、
                           resolve_option_patterns、C gen_match 求值式先行 + Option 改写
  tools/rosoto_native.py   lower_match 求值式先行 + Option 模式改写（PE/AArch64 零改动）
  tests/run_native_tests.sh / tests/run_win_tests.py   登记 t19（native [13] + PE + 交叉验证）
新增：
  tests/t19_option.ros     option[int]/option[str] 构造、函数返回、Option.Some/None 解构

测试：
  Windows 57 ✅ | native Linux 54 ✅ | C 16 ✅ | corelib 34 ✅ | io_uring 26 ✅（总 187）
```
