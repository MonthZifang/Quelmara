# v3.57 — `map[K]V.new()` 容量可省略；覆盖率 59 → 60

- 日期：2026-11-01
- 任务：用户要求"继续"；本打算做 `xmm_load`，评估后改做低成本项
- 影响面：`bootstrap/qlmc/qlmc.qma`（`map.new` 解析）、
  `tests/t201_qlmc_mapnew.qma`、`tests/qlmc_test.py`、
  `tools/dev/qlmc_coverage.py`（`BASELINE` 59 → 60）
- 覆盖率：**59 → 60**（`std/session`）
- 回归：PASS=370 FAIL=0 SKIP=0；qlmc 差分 78 → **80**

## 为什么没做 `xmm_load`

原计划做 `xmm_load`（挡 `std/aes` + `std/tls13`，收益 59 → 61）。评估后发现
它不是一个内建，而是**一整条 SIMD 轨道**：

```
std/aes 需要的：xmm_load, xmm_store, xmm_mov, xmm_pxor,
                pand, por, pshufb, pclmulqdq,
                aesenc, aesenclast, cpu_aes, cpu_pclmul
```

12 个内建，且涉及新增 SSE 指令编码路径（`movdqu`/`movsd` 的 mem 形态、
XMM 寄存器分配、AES-NI 编码）。这是和前面几个内建**不同量级**的改动，
不适合塞进一个版本。

而且 `TlsClientResult`（挡 `std/tls_net` + `std/httpc_net`，收益 +2）也走不通 ——
它依赖 `std/tls_client` 先能编，而 `std/tls_client` 自己就卡在 `xmm_mov`。
**这条链是死结，必须等 SIMD 轨道。**

所以转向 `std/session`：独立、纯解析问题、成本低。

## 问题：`map[K]V.new()` 强制要求容量

```quelmara
struct SessionStore {
    data: map[str]str
    exp: map[int]int
}

pub fn session_new() -> SessionStore {
    return SessionStore {
        data: map[str]str.new(),      // ← qlmc: "期望表达式"
        exp: map[int]int.new()
    }
}
```

qlmc 的 `map.new` 解析强制 `_expr(p, pos)` 读容量，省略就报错。
而 stage-0 的 `qlm.py` 注释写着 **"cap 须 2 的幂，省略默认 16"** ——
基准一直允许省略。

## 修复

```quelmara
let mut cnt = -1
if !_is_p(p, pos, P_RPAREN) {
    cnt = _expr(p, pos)
}
_eat_p(p, pos, P_RPAREN)
if cnt < 0 {
    cnt = _node(p, E_NUM, 16, -1, -1)     // 默认 16，与 stage-0 一致
}
```

## 测试

`tests/t201_qlmc_mapnew.qma`，加进 `tests/qlmc_test.py` 的 `CASES`
作为**差分用例**（`s34_mapnew`），10 行输出与 stage-0 逐字节一致。

四条判据：

| 判据 | 抓什么 |
|---|---|
| 省略容量能 set/get/has | 默认值真的生效 |
| 装 12 个键（`cnt=12`、`sum=78`） | 默认 16 够用，不是退化成 1 或 0 |
| 显式 `new(4)` 仍生效 | 加默认值时没把参数忽略掉 |
| 结构体字面量里用 | `std/session` 的真实形态 |

### 写测试时撞到的三个 qlmc 缺口（都不在本版范围）

1. **`s.a.set(...)`（结构体字段上直接调方法）** —— qlmc 报"期望表达式"。
   改成 `let ma = s.a; ma.set(...)`。
2. **`struct` 必须前置声明** —— qlmc 不支持"先用在声明前"，stage-0 允许。
   把 `struct Holder` 挪到 `main` 之前。
3. **`print(bool)` / `bool.to_str()` 格式不同** —— stage-0 给 `true`/`false`，
   qlmc 给 `1`/`0`。改成 `if` 分支输出固定字符串。

前两个是真实缺口，值得后续补；第三个是既有差异，需要决定以哪边为准。

## 覆盖率

`std/` **59 → 60**：`std/session.qma` 解锁。`BASELINE` 已上调到 60。

剩余 10 个模块：

```
2  缺内建: xmm_load           (std/aes, std/tls13)      ← 需 SIMD 轨道
2  未知类型 TlsClientResult   (std/httpc_net, std/tls_net) ← 依赖 tls_client，也是 SIMD 死结
1  vec[vec[T]] §7.18          (std/csv)
1  泛型 [T: Ord]              (std/gen)
1  函数重复定义 _fail         (std/http)
1  函数重复定义 _get          (std/logfile)
1  缺内建: syscall            (std/park_linux)          ← Linux 专用
1  缺内建: xmm_mov            (std/tls_client)          ← 需 SIMD 轨道
```

**剩下的 10 个里，4 个（40%）都卡在 SIMD**。要再往前推，
必须专门做一版 SIMD 支持 —— 那是下一个真正的大件。

## 自举

30/30 组等价 + 不动点成立。stage-2 产物 647680 B，仍在 `ARENA_CAP = 4 MB`
余量内。
