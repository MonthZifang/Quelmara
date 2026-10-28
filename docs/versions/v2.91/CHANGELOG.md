# v2.91 — C 后端的三个缺口：DCE 漏扫结构体字面量、函数值与 libc 撞名

- 日期：2026-10-28
- 任务：修 lint/回归 —— 让 **C 后端回归第一次真正全绿**（`PASS=15 FAIL=0`）
- 结论：`tests/run_tests.sh` 里那条 `❌ echo_server 编译失败` 不是环境问题，
  是**三个独立缺陷叠在一起**，外加一个从 v0.1 起就不存在的示例 API。

## 怎么发现的

本机原来没有 C 编译器，所以 `run_tests.sh`（C 后端回归）从来没在这里跑过；
CI 上它一直红着，而红的原因被 `❌ echo 并发测试失败` 这样的下游症状盖住了。
这次把一个独立 gcc-12 装进工具链（复用的 Debian deb，解到 `toolchain/gcc`，
`--sysroot` 指向它，不需要 root），第一次在本机跑通这条链，于是三个缺陷
按顺序暴露出来。

> **装 C 编译器本身也有个坑值得记**：`/tmp` 在这个环境里是 `noexec` 挂载，
> 解出来的 `gcc`/`as`/`ld` 全部 `Permission denied`。挪到工作区下才跑得起来。

## 缺陷一：全局 DCE 漏扫 `structlit` 的字段（最严重）

`global_dce` 的引用收集 `walk()` 只认 `tuple` 和 `list`：

```python
def walk(e, refs, methods):
    if isinstance(e, tuple): ...
    elif isinstance(e, list): ...
    # 没有 dict 分支
```

而结构体字面量的 AST 形状是

```python
('structlit', ['Server'], {'on_data': ('name', 'handler')})   # ← 第三个是 dict
```

于是**结构体字面量里的所有引用整片漏扫**。后果不是"多留一个函数"，而是
**把回调函数当死代码删掉**：

```
fn handler(p: int) -> int { ... }
fn main() { let s = Server { port: 41, on_data: handler } }
```

`handler` 只以"裸名"出现在 `structlit` 的 dict 里 → DCE 认为它不可达 → 删掉
→ 下游要么报 `'handler' undeclared`（C 后端），要么报 `未定义变量 handler`
（自研后端）。

**两个后端共用这份 DCE**，所以这是语言级缺陷，不只是 C 后端的问题 —— 只是
C 后端的报错更晚、更像"名字写错"。

修复：`walk()` 增加 `dict` 分支，遍历 `values()`。

## 缺陷二：用户函数名不加前缀，与 libc 正面撞名

C 后端把 Quelmara 函数名**原样**写成 C 符号。`std/net.qma` 里有 `pub fn send`，
生成出来就是

```c
static int64_t send(int64_t conn, const char * data);
```

而 `#include <unistd.h>` 在用户代码**之前**展开，于是 gcc 报：

```
error: conflicting types for 'send'; have 'int64_t(int64_t, const char*)'
```

`send`/`read`/`open`/`index`/`time`/`listen` 这类名字全中招。这是"交叉验证
后端"的定位问题：它要能编真实标准库，就必须有自己的命名空间。

修复：用户函数统一加 `u_` 前缀（`Codegen.cfn`）。**只给真正的用户函数加** ——
内置（`mem_load64` 之类）保持原名，否则会把"这条路径还没实现"伪装成
"未定义符号"，一个报错点炸成一片（实测就是 `void h = u_mem_load64(...)`：
因为查不到返回类型，类型都推成 `void`）。

## 缺陷三：裸函数名当值 / 通过变量间接调用

两条相关但不同的路径，C 后端都没处理：

| 写法 | 以前的产物 | 现在 |
|---|---|---|
| `let s = S { cb: hello }` | `hello`（未声明标识符） | `u_hello` |
| `fn apply(f: int, v: int) { f(v) }` | `u_f(v)`（把形参当函数） | `((int64_t(*)(int64_t))(f))(v)` |
| `spawn handle(conn)` | `handle(...)`（未声明） | `u_handle(...)` |

自研后端一直是对的（它发 `fnaddr` / `callr`），所以这三处都是 C 后端独有的缺口。

第二条要注意**作用域优先级**：`fn apply(f: int, ...)` 里的 `f` 是形参，
而 `fn f(...)` 也可能是真函数。调用点必须先查环境（局部优先），再当函数处理 ——
反过来就会把 `f(v)` 生成成 `u_f(v)`，把能跑的代码改坏。

## 缺陷四（不是缺陷）：`echo_server.qma` 用的 API 从来没存在过

`examples/echo_server.qma` 从 v0.1 起就写着：

```quelmara
let server = net.TcpServer {
    on_connect: on_connect
    ...
}
server.serve()
```

而 `std/net.qma` 的第二行一直写着"SPEC 的 net.TcpServer reactor …**仍是目标模型**"
—— 也就是说这个文件是**设计草图**，从未实现。`net.Conn` / `net.Action` 同样不存在。

实际可用的是 `std/net/reactor.qma` 的 `serve(port, backlog, on_connect, on_data, on_close)`，
回调收**裸 fd**、直接 `send`/`recv`，没有富对象包装。

处置：把示例改写成真实 API（保留"高并发 echo"这个用途），并在文件头写明它为什么
被重写。不是删掉 —— 用户点开 `examples/` 想看的正是"怎么写一个服务器"。

## 回归：C 后端从此可以断言"全绿"

`tests/run_tests.sh` 的 `[4]` 段原来编 `echo_server.qma` 并起 9000 端口跑 20 并发回显。
即使示例修好了，它在 C 链路上**仍然不可能通过**：C99 后端没有任何 `tcp_*` 内建
（`tcp_listen`/`tcp_accept`/`tcp_send`/`tcp_recv`/`tcp_close` 全靠自研后端发射，
C 后端只有 `tcp_nodelay`）。

于是把这一段改成**按能力探测**：C 后端有 `tcp_listen` 就真跑，没有就 SKIP 并说明
网络回归该看哪条链（`tests/test_uring.sh` 的 io_uring）。天天红着的一条 SKIP 比
一条假绿更糟 —— 它会让整条 C 回归的可信度一起作废。

## 实测

| 项 | 修复前 | 修复后 |
|---|---|---|
| `tests/run_tests.sh`（C 后端） | PASS=15 **FAIL=2** | **PASS=15 FAIL=0** |
| `tests/run_native_tests.sh`（自研后端） | PASS=67 **FAIL=34**（缺 C 编译器） | **PASS=101 FAIL=0** |
| `tests/lexdiff.py` | PASS=307 FAIL=0 | PASS=307 FAIL=0 |
| `tests/parsediff.py` | PASS=211 FAIL=0 | PASS=211 FAIL=0 |
| 五道门禁 | PASS | PASS |

`run_native_tests.sh` 从 67 涨到 101：多出来的 34 条正是以前因缺 `cc` 而红的
C 侧交叉验证项，现在全部真跑真过。

## 边界（未做）

| 项 | 现状 |
|---|---|
| C 后端的 `tcp_*` | 未实现，且不在路线里（C 后端只做交叉验证；网络走自研后端 / io_uring） |
| C 后端的 `mem_alloc`/`mem_load64`/`static_word` | 未实现 → `import std.net.reactor` 在 C 链路上编不过（已由 `[4]` 的探测如实记 SKIP） |
| 间接调用的返回类型 | 按 `int64_t` 处理（无签名信息，与自研后端 `callr` 同一信任级）；聚合返回值不可间接调用 |
| `u_` 前缀的可读性 | 生成的 C 更难读一点。但它是**生成物**，不是手写代码；且换来的是"任何用户函数名都不会撞 libc" |

## 口径

本版是正确性修复，没有性能数字。基准与 v2.89 相同，见 `docs/06-status.md` §3.52。
