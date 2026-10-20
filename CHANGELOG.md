# Rosoto 更新日志（CHANGELOG）

> 产品后端 = 自研后端（Linux x86_64 ELF / Windows PE32+ / AArch64）；
> C99 后端仅作交叉验证。格式：每版本记录「特性 / 优化 / 修复 / 回归规模」。

---

## v0.11 — 2026-10-20 任务/通道语法补全（工作区，待提交）

### 新特性

- **`h.join()` 方法式语法**：与函数式 `join(h)` 完全等价（解析期脱糖，
  用户自定义 join 函数优先）；支持 `spawn f(x).join()` 直连式（t24）。
- **`chan.close()`**（t25）：控制块新增 `closed` 字（自研后端布局扩为 7 字）。
  - close 后 `send` fail-fast（stderr + 退出码 1）；重复 close fail-fast；
  - `recv` 排空缓存数据后返回 0（零值）；关闭只阻止新 send，不动已缓存数据；
  - C 端广播唤醒全部等待方，自研端 spin+yield 循环重检。
- **`chan select`**（t26）：`select { c1.recv(), c2.recv() }` 表达式，
  返回首个就绪臂的值。轮询 + yield（C 端 usleep 100µs）；声明序优先；
  全部关闭且排空返回 0；关闭的空臂被跳过。非阻塞取数走
  `try_recv(h, &ok)` 出参协议（自研后端帧槽传址）。

### 验证

- Windows PE：59 项全绿（t24/t25/t26 + 2 个 fail-fast 退出码用例）；
- native runner 新增 [18] join 方法式 / [19] chan close / [20] select 段
  （native + C 双跑 + 双链 diff，需 Linux 环境执行）。

---

## v0.10 — 2026-10-20 map[K]V + 浮点运算（工作区，待提交）

### 新特性

- **`map[K]V` 开放寻址哈希表**（K ∈ int/bool/str，V ∈ int/str）：
  `map[K]V.new(cap)` 构造、`set/get/has/del/len`、覆盖写、str 键内容相等判定、
  cap=16 起步插 200 键自动扩容、删除后墓碑复用、map 作函数参数/返回值（句柄传递）、
  arena 块内绑定。缺失键 `get` fail-fast（回归 [16]，自研/C 三链）。
- **浮点实际运算**（`float` = f64，`f` 后缀 = f32）：字面量 / 四则运算 / 比较 /
  `to_int` / `to_float` / 一元负号 / 函数参数与返回值 / `to_str()`，
  格式化与 C 端 `rosoto_f64_to_str` 算法逐位一致：`[1e-6, 1e12)` 定点 6 位小数去尾零，
  其余科学计数 `d.dddddde±N`，nan/inf/-inf/0 特判（回归 [17]，自研/C 三链）。

### 修复

- **自研后端 `__f64_to_str` 科学计数法死循环**（潜伏 bug）：IR 非 SSA，
  两个归一化循环（`x/=10` 降位数 / `x*=10` 升位数）曾写入新 vreg 再 rebind
  Python 变量，循环条件读到的仍是旧 vreg → 进入科学计数路径即无限循环
  （`print(0.0000001)` / `print(1e12)` 挂死）。改为原地更新（`dst==src`，
  同 itoa 的 `div v,v,10` 模式）后修复；C 端本来就是真 while 循环，不受影响。

### 验证

- Windows PE：[1]–[6] 段 **52 项本机全绿**（含新增 float 用例）；
  [7] PE×ELF 交叉验证表已登记 t22/t23（共 13 项，需 WSL 环境执行）。
- 自研 Linux：native runner 新增 [16] map 3 项 + [17] 浮点 3 项（需 Linux 执行）。

---

## v0.9 — 2026-10-20 性能轮（工作区，待提交）

**基准**（Xeon E5-2666 v3 / WSL2 / gcc 15.2，`tests/bench.sh` best-of-3）：

| 基准 | v0.8 自研 | **v0.9 自研** | gcc -O2 / pthread | 原目标 |
|---|---|---|---|---|
| loop_sum 2 亿热循环 | 380–518 ms | **11–13 ms** | 231 ms | 80 ms ✅ |
| parfor_sum 6M 任务 / 3 核 | 388–620 ms | **29–35 ms** | 131 ms | 50 ms ✅ |

### 优化

- **模块级数求和折叠 `opt_modsum`（新 pass，`tools/rosoto_opt.py`）**
  规范归约循环 `acc += (x0 + s·j) mod D`（gcd(s,D)=1 且 x 非负已证）整体折叠：
  - 整周期块：任意连续 U=D 项余数是 0..D-1 的排列 ⇒ 每块贡献常量 `D(D-1)/2`，
    `B = N//U` 块直接折叠成 `acc += B·D(D-1)/2`（N 编译期常量时继续常量折叠）；
  - 尾部 R<U 项：s=1 走无除法闭式 `R·tB + R(R-1)/2 − D·max(0, tB+R−D)`；
    s>1 保留只跑 R 次的 peel 小循环；
  - 归约按 2^64 环面同态，回绕语义与逐项累加严格一致。
  - 边界：gcd(s,D)>1 / 迭代数非编译期常量 / x 非负不可证 → 整体放弃，语义不变。
- **范围分析扩展（`analyze_nonneg` + `lower_parfor`）**
  - parfor worker 形参范围：clone() 调用点均为编译期常量块界 → `arg_ranges` 元数据；
  - `for` 形态 `jcc ge` 守卫与 `while` 形态统一按 `i < hi` 做上界证明；
  - 双 vreg 加法传播（如 `i*C + k`）、形参初始化归纳变量；
  - 效果：worker 热循环里有符号魔数除法的双重符号修正链整体消除（parfor 原 4 倍差距的主因）。
- **乘常数编码修复（`tools/rosoto_native.py`，潜伏 bug）**
  `mul_const` 回退路径（lea 链规划失败时）曾把 `x*C` 静默编码成 `x*x`——常数被丢弃。
  新增 `Enc.imul_rri`（三操作数 `imul r64, r64, imm32`）修正；历史上任何
  lea 链规划不下的常量乘法都会错编，本轮由 modsum 闭式代码首次触发并修复。

### 验证

- 回归 **198 项全绿**：Windows PE 61 / 自研 Linux 61 / C 16 / corelib 34 / io_uring 26（本地 + 机器上各跑一遍）；
- modsum 差分模糊 **180 例**：优化 ≡ 无优化 ≡ Python 真值（含负值门控组，覆盖放弃路径）。

### 未发布（工作区既有内容，随本轮一起进入快照）

- `result[T,E]` 泛型单态化 + `?` 传播 + match 解构（回归 [14]，三链全绿）；
- `[]T` 切片：{ptr,len} 两字零拷贝视图 + 聚合 ABI + 动态越界 fail-fast（回归 [15]，三链全绿）。

---

## v0.8 — 2026-10-19 19:59 `option[T]` 受控单态化

- `option[int/bool/str]` 跨 native / Windows PE / C 三链：`option[T].some(x)/.none()` 构造、
  `Option.Some(v)/Option.None` match 解构、函数返回 `option[T]`（复用枚举聚合 ABI）。
- 实现 = 前端合成真枚举 `__opt_<T>` + 构造脱糖 `enumlit` + 模式按求值式真实枚举名改写；后端零改动。
- 回归 187 项全绿（Windows 57 / native 54 / C 16 / corelib 34 / io_uring 26）。

## v0.7 — 2026-10-19 18:21 Result 错误传播 + 保守范围分析

- 用户定义 `Result` 枚举 + `?` 传播三链打通；`Ok` tag 按声明顺序取，不再硬编码 0。
- 自研优化器：严格递增常量上界循环的非负范围传播，安全消除有符号魔数除法符号修正链；
  parfor/spawn worker 保留 `no_inline` 寄存器分配边界。
- 回归 183 项全绿。

## v0.6 — 2026-10-19 14:29 定长数组 `[N]T`

- 帧上连续 N 字、动态下标、值语义拷贝、越界 fail-fast（`bounds_check` 编译期开关）。
- 数组作参数/返回值明确报错（切片见未发布项）。回归 180 项全绿。

## v0.5 — 2026-10-19 14:22 `chan[T]` 有界 MPMC 通道

- 48 字节控制块 + `xchg` 自旋锁 + yield；C 后端条件变量等价实现。
- 运行库按需发射：只用到的 arena/join/chan 才进产物。回归 172 项全绿。

## v0.4 — 2026-10-19 13:46 `spawn`/`join` 任务并行 + arena 帧级回收

- `spawn f(args)` + `join(h)`；Linux raw `clone()` / Windows `CreateThread` / C pthread。
- arena 回卷 bump 指针，块内分配一次性回收。回归 165 项全绿。

## v0.3 — 2026-10-19 13:01 自研 Windows x86_64 PE/COFF 后端

- 同一 RosIR → PE32+ / COFF + kernel32 导入 + DIR64 重定位，无 CRT，产物 6–26 KB。
- 回归 152 项全绿。

## v0.1–v0.2（此前）

- v0.1：Rosoto → RosIR → 优化 passes → 线性扫描寄存器分配 → 自研指令编码器 → 裸 ELF64；
  魔数除法（mulhi+移位）、常量折叠、复制传播、DCE、cmp+jcc 融合、帧槽复用。
- v0.2：RosIR 优化器成型（LICM / CSE / 循环展开 / 指令调度 / 强度削减）、内联、
  运行库 RosIR 自举（print/itoa/strlen/alloc）。

---

*维护约定：性能改动必须附 `tests/bench.sh` 基线对比 + 全量回归数字；
优化 pass 不满足证明条件时必须安全放弃，语义等价由 C 后端交叉验证兜底。*
