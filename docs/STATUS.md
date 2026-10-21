# Quelmara 状态总表（语言 / 工程化 / 性能 / 平台）

> 口径：2026-10-21，`v1.10` 工作区（未提交内容含 v1.3 / v1.5 / v1.6 / v1.10）。
> **本文只回答"现在到哪了"**。缺口的详细论证在 `docs/GAPS.md`，
> 每个特性的精确语义在 `docs/LANG.md`，版本变更在 `CHANGELOG.md`。
>
> 纪律：本文每一行的"有/无"都必须能由 `复核命令` 一节里的命令复现；
> 写不出证据的一律标 🚧（规范已定、实现未做），不标 ✅。

---

## 0. 一句话结论

> **后端像 1.0，语言像 0.7，工程化像 0.4，生态像 0.1。**
>
> 编译器本体（手写 x86-64 编码、ELF/PE 写出、IOCP reactor、四套自举对拍）
> 比绝大多数 hobby 项目扎实一个数量级；但**语言层长期欠账**（泛型、接口动态分发、
> 所有权检查）和**工程化欠账**（包管理、调试器、LSP）才是"能不能用来写真实项目"的分水岭。
> v1.8 把语言层从 0.4 拉到 0.6：整数宽度、`@simd`、`@no_preempt`、`rc[T]`、
> 所有权检查、`interface`（静态分发）都落地了，并且修掉了三个必现误编译。
> v1.9 补上最后一块语言拼图：**接口值的 vtable 动态分发**（`let s: Shape = Circle{..}`、
> `vec[Shape]`、接口形参/返回值），现在"多态"真的能用了。
> v1.10 打下并发地基：`atomic_add/cas`（lock 前缀，一条 CPU 指令直达）+
> `std/sync`（自旋锁 / Treiber 无锁栈 / WaitGroup，全 Quelmara 自实现）+
> `now_cycle()`（rdtsc 自计时）——mutex 无竞争 28 cycles/iter，无 libc 间接。

---

## 1. 语言状态

### 1.1 特性矩阵

| 能力 | 状态 | 证据（可跑） | 边界 |
|---|---|---|---|
| 标量 / 控制流 / 函数 | ✅ | `tests/t1.qma` … `tests/t20.qma` | C 风格，无 `switch`（用 `match`） |
| `struct` / `enum` / `match` | ✅ | `tests/t10_match.qma`、`t37_vecagg.qma` | `match` 必须穷尽 |
| `vec[T]` | ✅ | `tests/t37_vecagg.qma`、`t57_vecnest.qma` | 元素：标量 / struct / enum / **嵌套 vec（v1.12，句柄语义）**；`vec[map]` ❌ |
| `map[K]V` | ✅ | `tests/t25_map.qma` | K/V 仅 int/bool/str |
| `option[T]` / `result[T,E]` / `?` | ✅ | `tests/t31_result.qma`、`t34_option.qma` | 受控单态化，载荷限标量 |
| 切片 `[]T` / 定长数组 `[N]T` | ✅ | `tests/t21_slice.qma`、`t36_arrparam.qma` | 数组值语义；切片是零拷贝视图 |
| `chan[T]` / `spawn` / `parfor` | ✅ | `tests/t18_chan.qma`、`examples/parfor_sum.qma` | 有界 MPMC + 自旋锁 |
| **atomic 原语 + std/sync** | ✅ **v1.10** | `tests/t55_sync.qma`、`bench/sync_bench.qma` | `atomic_add/cas/fence`（lock 前缀）+ 自旋锁/Treiber 栈/WaitGroup；AArch64 未接（明确报错）；栈 pop 单消费者（多消费者 ABA 见 GAPS） |
| `now_cycle()`（rdtsc） | ✅ **v1.10** | `bench/sync_bench.qma` | 周期计数非纳秒；程序内自计时排除冷启动 |
| `import`（扁平合并） | ✅ | `std/http.qma` 自身 | 无命名空间、无版本、无包管理 |
| 函数值 + `callr` | 🟡 | `tests/t38_callr.qma` | ≤6 参、实参不能是 struct/slice、无捕获（无闭包） |
| **真实整数宽度 `u8..u32/i8..i32`** | ✅ **v1.8** | `tests/t49_width.qma` | 见 §1.2：边界截断，表达式内按 C 提升 |
| **`let x: T` 类型标注** | ✅ **v1.8** | `tests/t49_width.qma` | 只用于宽度类型与文档；不是完整类型检查 |
| **`@simd` 归约** | ✅ **v1.8** | `tests/t50_simd.qma` | **只认** `acc += a[i]` 形状的 `[N]int` 归约（SSE2 两路） |
| **`@no_preempt`** | ✅ **v1.8** | `tests/t50_simd.qma` | 抑制编译器插入的 `sched_yield`；不是内核抢占 |
| **`rc[T]`** | ✅ **v1.8** | `tests/t51_rc.qma` | 载荷仅具名 struct；不自动 drop |
| **所有权 / 借用检查** | 🟡 **v1.8** | `tests/bad/own_*.qma`（必须编译失败） | **只查 `rc[T]` 句柄**的 use-after-drop / double-drop / move-then-use；不漏检堆/引用别名 |
| **`interface` / `impl`** | ✅ **v1.9** | `tests/t52_iface.qma`（静态）、`t54_iface_dyn.qma`（动态） | 契约 + 校验 + 静态分发 + **vtable 动态分发**（接口值 / 接口形参 / 返回值 / `vec[Shape]`） |
| **用户泛型（`fn f[T]`）** | 🟡 **v1.11 单态化落地**：单 T + 显式实例化 `f[int](...)`，编译期复制成具名实例（零分发开销）；自递归 / `T{...}` 字面量 / `vec[T]` 形参可用（`tests/t56_generic.qma`） | 类型推导 / 多参 / 约束 / 泛型 struct 未做（`docs/GAPS.md §2`） | 此前只能复制粘贴 + 命名前缀 | **P1（推导）** |
| 闭包 / 捕获 | ❌ | 同上 | 只能传函数名 |
| FFI（`@extern("C")`） | ❌ 自研后端 | `CHANGELOG` v0.12 | C 后端有原型；自研后端显式拒绝（无动态链接器） |
| **编译期求值（const）** | 🟡 **v1.11 整型算术**：`const N = 4 * KB`（+ - * / % 括号 + const 引用，C 截断语义，解析期求值）（`tests/t56_generic.qma`） | `const fn`（编译期执行纯函数）未做；float/str/bool 仍仅字面量 | 手算后写字面量 |
| **宏系统** | ❌ | `docs/GAPS.md §2` | 需要编译期 AST API 基建；路线在 P2 | — |
| **运行时反射** | ❌ | `docs/GAPS.md §2` | 需要类型元数据段；P2 | — |

### 1.2 整数宽度的准确语义（v1.8）

值统一用 64 位寄存器承载；**只在边界截断**：

| 边界 | 行为 |
|---|---|
| `let x: u8 = expr` | 结果 `& 0xFF`（零扩展） |
| `x = expr`（x 为窄变量） | 同上 |
| 形参 `fn f(x: u8)` | **入口**截断（调用方可以传 300，进来是 44） |
| 返回值 `-> i8` | **出口**截断（`127+1` 返回 `-128`） |
| 表达式内部 | **不截断**，按 C 语义提升到 64 位（`u8 200 + 100 == 300`） |

未覆盖：struct 字段存窄值时**不截断**（字段类型目前只用于布局），
`vec[u8]` 元素等价于 8 字节槽。两条都记在 `docs/GAPS.md §2`。

### 1.3 `interface` 做到哪一步（v1.9 起：真多态）

```quelmara
interface Shape { fn area(self) -> int }

let s: Shape = Circle { r: 3 }   // 隐式装箱 {data, vt}
print(s.area())                  // vt[slot] -> callr（运行期派发）

let v = vec[Shape].new(4)        // 异构容器
v.push(Circle { r: 1 })
v.push(Rect { w: 2, h: 3 })
for x in v { print(x.area()) }   // 各回各家
```

- ✅ 契约声明、`impl` 完整性/签名检查（缺方法、参数、返回类型不匹配 → 编译失败）
- ✅ **静态分发**：接收者类型编译期已知 ⇒ 直接调用，零开销
- ✅ **动态分发**：接口值 = `{data, vt}` 两字；`vt[slot]` 取函数指针 + `callr`
- ✅ 隐式装箱四处：`let` 标注、函数实参、`vec[Shape].push`、`return`
- ✅ `vec[Shape]` / 接口形参 / 接口返回值 / 方法返回聚合 / 链式 `pick().area()`
- ❌ 装箱内存不释放（无引用计数、无 drop；需要共享请用 `rc[T]`）
- ❌ 同一类型在两个接口里同名方法 → 编译错误（无消歧义规则）
- ❌ C 后端（`--target c`）不支持 `interface`/`impl`

> 结论：**能当多态用了**。代价是装箱时一次 `__alloc` + payload 拷贝，
> 且这些内存随进程存活（当前无回收）。

## 2. 工程化状态

| 环节 | 状态 | 现状 | 缺什么 |
|---|---|---|---|
| 编译驱动 | ✅ | `tools/stage0/qlm_cli.py`（build/run/test/fmt） | 增量编译、并行编译 |
| 构建配置 | ✅ | `Quelmara.toml`（内存上限/核数/越界检查） | 依赖声明、profile、交叉编译目标 |
| 回归 | ✅ | PE **113 项**、词法 102/102、声明级 88/88（2 跳过）、IR 50/50、发射 10/10 | 协议库回归、压测进 CI |
| 门禁 | ✅ | `check_names` / `check_origin` / `check_docs`（均进 CI 双 job） | 性能回归门禁（防劣化） |
| CI | ✅ | `.github/workflows/ci.yml`：Linux 五套 + Windows PE | 无覆盖率、无 fuzz、无 nightly bench |
| 自举 | 🟡 2/9 | 词法 + 声明级 parser 已对拍；1770/18909 行 = 8.6% | 函数体 parser、typeck、IR、编码器 |
| 包管理 | ❌ | `import` 是扁平合并本地文件 | 依赖图、版本、registry、锁文件 |
| 库归档 | ❌ | `.qla` 仍"规划中" | 预编译产物 + 版本化 ABI |
| 调试器 | ❌ | 靠 `gdb` / `readelf` / `capstone` 外部工具 | DWARF、断点、变量查看 |
| LSP / 补全 | ❌ | 无 | 语义索引、跳转、重命名 |
| 格式化 | 🟡 | `qlm_fmt.py`（基础排版） | 幂等性测试、注释保留策略 |
| 文档生成 | ❌ | 无 | doc comment 提取 |
| 发布 | 🟡 | 单文件 `.qex`（无运行时依赖） | 签名、安装器、版本渠道 |

---

## 3. 性能状态

> 全部为本机（Windows / x86-64）进程内 `now_ns()` 计时，**绝对值只做纵向比较**。
> 完整方法学与基准源码见 `docs/PERF.md` 与 `bench/`。

| 负载 | 实测 | 对比 | 判断 |
|---|---|---|---|
| `loop_sum` 1e8（可闭式折叠） | 11–13 ms | gcc -O2 231 ms | **赢**（但这是优化器把整段折叠了，不代表通用代码） |
| 整数归约 4096 元素 ×200 | 3–4 µs/次 | `@simd` 1 µs/次 | **@simd 3–4× 标量**（`bench/simd_bench.qma`） |
| SHA-256 1 MiB | 71 ms（14.7 MB/s） | OpenSSL 同机 300–500 MB/s | **输 20–30×**，瓶颈是标量轮函数 |
| `str_split`+`join` 1 MiB | 30 ms（28 MB/s） | Go `strings` 同量级任务约 3–5 ms | **输 6–10×** |
| JSON 92.9 KB / 2000 对象 | 4–11 ms | Go `encoding/json` 约 0.6–1 ms | **输 5–10×** |
| gzip 1 MiB 重复文本 | 117 ms，137× | zlib -6 约 15–25 ms | **输 5×**（CRC 逐位 + 固定 Huffman） |
| AES-128-GCM | 仅握手级可用 | AES-NI 数十 GB/s | **输 2 个数量级**（GHASH 逐位） |

**为什么还没"全面赢过 C/Go"**：

1. **没有寄存器分配级别的全局优化**（LICM 默认关闭，见 §5 已知约束）；
2. **没有 SIMD 自动向量化**——`@simd` 是手写触发的单形状，不是向量化器；
3. **没有查表化的密码学/压缩内核**（S-box 运行时生成、GHASH 逐位、CRC 逐位）；
4. 标量代码本身不差（`loop_sum` 之外的整型循环与 gcc -O2 同量级），
   差的是**库内核**与**循环级优化**。

> 想真正赢，顺序是：修完剩余 codegen 洞 → 重开 LICM 并压测 → 动态长度越界消除 →
> 密码学/压缩查表化 → 向量化器。**在任何一步之前宣称"赢过 C/Go"都是不诚实的。**

---

## 4. 平台状态

| 平台 | 状态 | 证据 | 边界 |
|---|---|---|---|
| Windows x86-64（PE32+） | ✅ 主平台 | `tests/run_win_tests.py` 113 项 | 无 CRT，只导入 kernel32/ws2_32 |
| Linux x86-64（ELF64） | ✅ | `tests/run_native_tests.sh`（CI ubuntu） | 需 Linux 环境；本机沙箱被 WSL 黑名单拦住 → 交叉验证 SKIP |
| Linux io_uring | ✅ | `tests/test_uring.sh`（CI） | 仅 5.1+ 内核 |
| AArch64（ELF） | 🟡 | `tests/run_native_tests.sh` 模拟器执行级 | 无 chan/map/spawn；v1.8 新增 IR（`trunc`/`vsum`）、v1.9 vtable 动态分发、v1.10 atomic/rdtsc 尚未进 A64 发射层 → IR 对拍里显式 SKIP；A64 遇以上形态编译期明确报错（`qlm_arm64.py` gen_all 拦截） |
| macOS（Mach-O / kqueue） | ❌ | `docs/PLATFORM.md` 候选 | 无 |
| wasm32/64 | ❌ | 路线图 | 无 |
| TLS（https / wss） | 🟡 Phase A 2/3 | `docs/TLS.md` | SHA-256+HMAC ✅、AES-128-GCM ✅、X25519 ❌、握手 ❌ |

---

## 5. 已知约束与误编译

### 5.1 v1.8 修掉的三个误编译（已转正为回归）

| # | 症状 | 根因 | 回归 |
|---|---|---|---|
| 1 | 循环内 `substr` 长度来自调用结果 → 越界/错串（`--no-opt` 正常） | 内联路径把 `[rbp-8]` 的**栈偏移 8** 当成 **R8 寄存器号**比较，跳过 fetch | `tests/t53_regress.qma` |
| 2 | `"\xNN"`（≥0x80）被当 Unicode 码点再 UTF-8 编码 | 词法器 `chr(b)` + `encode("utf-8")` | `tests/t53_regress.qma` |
| 3 | 一个表达式里两次调用 + 下标 → 结果整体偏移 | 同 #1 | `tests/t53_regress.qma` |

> 教训写在 `docs/GAPS.md §6.5`：**看到"随机位置段错误"先怀疑自己越界写**，
> 最小化到 30 行内仍复现才算编译器 bug。

### 5.2 仍存在的约束

- **LICM 默认关闭**：x64 分配器布局敏感的段错误未根修（`QLM_ENABLE_LICM=1` 可开）。
- **`@simd` 不是向量化器**：只识别单一归约形状；切片 / `vec` / 浮点未覆盖。
- **`rc[T]` 不自动 drop**：所有权检查器只做线性检查，泄漏以**编译警告**给出。
- **接口装箱不释放**：每次 `let s: Shape = Circle{..}` 都 `__alloc` 一份 payload，
  没有回收路径；热点循环里频繁装箱会涨堆（需要池化/改 `rc[T]`）。

---

## 6. 复核命令（任何人可重跑）

```bash
# 语言特性（v1.8）
python tools/stage0/qlm_cli.py run tests/t49_width.qma  --target win   # 整数宽度
python tools/stage0/qlm_cli.py run tests/t50_simd.qma   --target win   # @simd / @no_preempt
python tools/stage0/qlm_cli.py run tests/t51_rc.qma     --target win   # rc[T]
python tools/stage0/qlm_cli.py run tests/t52_iface.qma  --target win   # interface 静态分发
python tools/stage0/qlm_cli.py run tests/t54_iface_dyn.qma --target win # interface 动态分发（vtable）
python tools/stage0/qlm_cli.py run tests/t53_regress.qma --target win  # 三个误编译的回归

# 负向：下面三条必须编译失败（所有权检查）
python tools/stage0/qlm_cli.py build tests/bad/own_use_after_drop.qma --target win
python tools/stage0/qlm_cli.py build tests/bad/own_double_drop.qma    --target win
python tools/stage0/qlm_cli.py build tests/bad/own_move_use.qma       --target win
python tools/stage0/qlm_cli.py build tests/bad/iface_no_impl.qma      --target win

# 全量
python tests/run_win_tests.py          # PE 回归
python tests/lexdiff.py                # 词法 99/99
python tests/parsediff.py              # 声明级 90/90（显式跳过 1 个 interface 文件）
python tests/irdiff.py                 # QuIR 架构无关
python tests/emitdiff.py               # 发射层确定性
python tools/dev/check_docs.py         # 文档漂移门禁
```

---

## 7. 下一步（按收益排序）

1. **用户泛型**（`fn f[T]` 单态化）：`vec/option/result/rc/interface` 之外，
   写自己的通用容器/算法。语言层最后一个大件。
2. **重开 LICM 并压测**：性能闸门，需要先补最小复现的回归网。
3. **接口装箱回收**：给装箱接 `rc` 或加 arena 作用域，否则热点路径会涨堆。
4. **文件系统 / 时间 / 随机 / 排序**最小集：工具类应用的前置（`docs/GAPS.md §3`）。
5. **X25519 + TLS 记录层**：https/wss 的最后一层。
6. **包管理**：`import` 之上做依赖图与版本，否则第三方库无从获取。

> 每完成一项：改本文 + `docs/GAPS.md` + `CHANGELOG.md`，跑 §6 的命令，再提交。
