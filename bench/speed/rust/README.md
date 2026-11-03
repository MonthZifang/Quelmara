# Rust 基准

**这里的源码还没有在本地验证过** —— 开发机没有 `rustc`。语法正确性由 CI
（`bench.yml` 的「额外对比语言」步骤装 rustup）验证。

写法规约（与 C / quelmara 版逐字等价）：

* 计时用 `Instant::now()` + `elapsed().as_nanos()`，与 `now_ns()` 同为单调时钟。
* 只打印「结果 + `T` + 纳秒耗时」三行。
* **溢出必须在三语言里语义一致**：C 用 `uint64_t` 回绕、quelmara 用 int64
  回绕，所以 Rust 这里显式用 `wrapping_mul` / `wrapping_add` / `wrapping_sub`
  —— 如果用普通 `*` / `+`，**debug 构建会 panic、release 构建是未定义行为**，
  与另外两种语言对不上。
* 伪随机序列的模数是 `% 2147483648`（2^31），三语言一致。

如果 CI 报某个文件语法错，改那一个就行 —— 它们之间没有共享代码。
