# v1.93 — `Drop`：作用域退出析构（`defer` / RAII / `Drop` 行翻绿）

- 日期：2026-10-24
- 任务：`07-gaps.md` §1「`defer` / RAII / `Drop`」🟡 → ✅。v1.48 只做了 `defer`
  （显式写清理），这一行剩下的半句是"仍无 `Drop`/析构——清理必须显式写"。
  本版把 `Drop` 补上：类型自己声明析构，作用域退出自动跑。
- 影响面：**语言层**（`qlm.py` 解析/内建接口/C 后端 fail-fast、`qlm_native.py`
  降级与 DCE、`qlm_opt` 无改动）、测试、基准、文档
- 版本号：v1.86–v1.92 已被并行轨（闭包 / FFI / 宏 / LSP / doc comment）占用，
  本版顺延为 v1.93

## 改了什么

`Drop` 是**内建接口**，不用自己声明：

```quelmara
struct Conn { fd: int }

impl Conn : Drop {
    fn drop(c: Conn) {
        if c.fd >= 0 { tcp_close(c.fd); c.fd = -1 }   // 幂等：写完置空
    }
}

fn use() {
    let fd = tcp_listen(8080)      // 先落局部变量（字面量里直接调函数是 §7.9 已知缺陷）
    let c = Conn { fd: fd }
    // ...
}                                  // 退出：自动 Conn__drop(c)
```

| 项 | 语义 |
|---|---|
| 声明 | `impl T : Drop { fn drop(t: T) { ... } }`：恰好一个接收者、无返回值 |
| 生效对象 | `let` 绑定的聚合变量（struct / enum）；泛型 `impl Box[T] : Drop` 按实例展开 |
| 触发点 | 块正常结束、`return`、`break`/`continue` 跳出该块 |
| 顺序 | 同块**逆序**；内层块先于外层；**在 `defer` 之后**（defer 里可能还在用变量） |
| 接收者 | 直接收**对象地址**（不经 `lower_call` 的聚合值拷贝），`c.fd = -1` 落在原对象上 |
| 移动 | `let b = a` / `return a`：析构责任随值转移，不双重析构 |
| 覆盖赋值 | `a = T { ... }`：先析构被覆盖的旧值 |
| 不析构 | 形参、容器元素、struct 字段、临时值（只泄漏、不悬垂） |
| 不跑 | `exit()`；C 后端整体不支持（fail-fast） |

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm.py` | `Parser.__init__` 预置内建接口 `Drop`（`drop(self) -> void`），用户直接写 `impl T : Drop`；`global_dce(fns_ast, keep=…)` 支持额外根（隐式调用）；**同一 `(类型, 接口)` 重复 impl 从静默覆盖改为编译报错**；C 后端对 `Drop` fail-fast |
| `tools/stage0/qlm_native.py` | 新增 `drop_table()`（DCE **之前**建表，签名不合规 fail-fast）；`Lower.drop_fns` / `drop_stack` / `_has_drop` / `emit_drop` / `_emit_drops` / `_drop_register` / `_drop_forget` / `_return_moved`；`block()` 里 `drop_stack` 与 `defer_stack` 同进同出；`let` 登记 + 移动转移；`return` / `break` / `continue` 退出点发射；结构体覆盖赋值先析构旧值；**顺带修** `match` 载荷绑定漏打 `vec`/`map`/`chan` 标签（枚举装缓冲区后 `buf.push` 报"方法未定义"） |
| `tests/t119_drop.qma` | **新增**：15 组断言（逆序 / 嵌套块 / return / break / continue / defer 顺序 / 两种移动 / 覆盖赋值 / 枚举析构 / 析构体写字段 / 形参不析构 / `continue`·`break` 早于 `let` / `match` 分支体） |
| `tests/bad/drop_arity.qma`、`tests/bad/drop_dupe.qma` | **新增**：析构多形参、重复 `impl Drop` 必须编译失败 |
| `bench/drop_bench.qma` | **新增**：五种写法的清理成本（无清理 / 手写 / `defer` / `Drop` / 空析构体） |
| `tests/run_win_tests.py` | 注册 `t119_drop` + 两个负向夹具 |
| `tests/parsediff.py` | `t119_drop` 进 `PARSE1_PENDING`（`impl` 家族，stage-1 未做 impl） |
| `docs/02-language.md` | §4.4 补内建接口 `Drop` 与重复 impl 规则；**新增 §8.7**（语义表 + 为什么"按绑定"而不是"按值唯一所有权" + 实现要点） |
| `docs/04-compiler.md` | **新增 §1.3**（`Drop` 降级链路：建表 → 保根 → 登记 → 发射；两个坑） |
| `docs/06-status.md` | **新增 §3.4h**（析构成本）+ §3.7 复现命令 + 回归/对拍行 |
| `docs/07-gaps.md` | §1 该行 🟡 → ✅ v1.93；P1 与推进顺序同步 |

## 两个坑（都是"静默错"，不是崩溃）

1. **析构表必须在全局 DCE 之前算**。`global_dce` 只认 AST 里的 `call`/`name`
   引用；析构是隐式调用，一个引用都没有。先 DCE 再建表 = 析构函数被当死代码删掉，
   程序正常跑、清理不执行。现在 `drop_table()` 在 DCE 前算好，并用
   `global_dce(keep=…)` 把析构函数钉成根。
2. **不能借 `lower_call` 发析构**。`lower_call` 对聚合实参一律"拷进临时帧槽再传地址"
   （值语义），析构就只能改到副本——`c.fd = -1` 白写、fd 还会被关两次。
   `emit_drop` 直接 `emit("call", None, name, [slot])`，把对象地址原样传过去。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | **PASS=265 FAIL=0 SKIP=1**（隔离副本跑"HEAD + 本版改动"；含新增 `t119_drop` + 2 个负向夹具；SKIP=WSL 交叉验证被本机沙箱拦。并行轨同一工作区仍在加用例，`06-status.md` 那一行由它维护，合并后以合并方复跑为准） |
| `python tools/stage0/qlm_cli.py run tests/t119_drop.qma --target win` | `drop ok`（15 组断言全过） |
| `python tests/irdiff.py` | **PASS=89 FAIL=0 SKIP=68**；`t119_drop` 不跳过——x86_64 与 aarch64 的 IR 逐字节相同（3623 行） |
| `python tests/parsediff.py` | **PASS=150 FAIL=2**（`t119_drop` 已进 `PARSE1_PENDING` 记账跳过；2 个 FAIL 是并行轨的接口夹具 `t118_iface_own` / `iface_rc_a64`，与本版无关） |
| `python tests/lexdiff.py` | **PASS=236 FAIL=0**（240 个源文件；本版不加记号，词法契约不变） |
| 无优化构建（`optimize=False`） | `drop ok`——析构不依赖优化 pass |
| 四道门禁 | check_names / check_origin / check_docs PASS |

## 性能（`bench/drop_bench.qma`，n = 2×10⁶，连续 6 轮按形状取最小）

| 写法 | ns/轮 |
|---|---|
| 无清理（基线） | 3.9 |
| 手写显式清理 | 8.9 |
| `defer` | 9.6 |
| **`Drop`** | **8.9** |
| 空析构体 | 3.9（内联后归零） |

结论：**一次析构 = 一次静态调用**——与手写调用同价（8.95 vs 8.93 ns），比 `defer` 省
约 0.7 ns/轮（省掉"已登记标志 + 退出点分支"）；空析构体被内联后完全消失，关内联时
+2.8 ns（纯调用开销，与 §3.4g 的原生调用基线一致）。没有 vtable、没有闭包。
选 `Drop` 是为了"忘了写清理也不会漏"，不是为了更快——但它确实不比手写慢。

## 已知边界 / 遗留

- **按绑定析构，不是按值唯一所有权**：形参、容器元素、struct 字段里的副本不析构
  （只泄漏、不悬垂）。要唯一所有权用 `rc[T]`（线性检查会盯住）。
- **无字段 drop glue**：struct 里装的资源要在自己的 `drop` 里显式释放。
- `exit(code)` 不跑析构；C 后端不支持 `Drop`（fail-fast，与 `defer` 同口径）。
- 泛型 `impl Box[T] : Drop` 可用（按实例展开），但**泛型 enum 的 Drop 未单独验证**。
- 版本号：`VERSION` 由并行轨同时推进，合并时以合并方为准。
