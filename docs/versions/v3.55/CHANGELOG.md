# v3.55 — `for k in map` + `map.del`；覆盖率 56 → 58

- 日期：2026-11-01
- 任务：用户要求"继续"；收 §7.40（`for k in map`）并补 `map.del`
- 影响面：`bootstrap/qlmc/qlmc.qma`（`S_FOREACH` 加 map 分支 + `_map_del`）、
  `tests/t199_qlmc_mapiter.qma`、`tests/qlmc_test.py`、
  `tools/dev/qlmc_coverage.py`（`BASELINE` 56 → 58）
- 覆盖率：**56 → 58**（`std/kv` + `std/set`）
- 回归：PASS=369 FAIL=0 SKIP=0；qlmc 差分 76 → **78**

## 两件事是一起补的

`std/kv` 和 `std/set` 同时需要 `for k in m` 与 `m.del(k)`，缺一个都过不去。

## 1. `for k in map`

map 布局（与 `_map_slot_of` 一致）：`[0]=cap`、`[8]=count`、`[16]=base`，
每槽 16 字节（key 8 + val 8），**键 0 表示空槽**。

遍历就是线性扫 `0..cap`、跳过键为 0 的槽 —— **不需要新增运行时例程**，
用现成的 `_vec_field` + `ADDRXN`（`dst = a + b*16`）就够。

键类型从 map 类型编码里取：`kty = (hty - TY_MAP) >> 8`。

**遍历顺序是槽序，不是插入序** —— 与 stage-0 的 `qlm_map_cap` /
`qlm_map_state` / `qlm_map_key_at` 同语义。所以 `for k in m` 的顺序
未定义，需要有序必须自己排序（`std/set` 的文档里也这么写着）。

## 2. `map.del`：一个会静默毁数据的坑

### 第一版是错的

最自然的实现是"找到槽 → 键清 0 → count-1"。但 **`_map_slot_of` 的线性
扫描一遇到"键为 0"就判定这是插入位并停止**。所以清 0 会**切断探测链**：

```
m.set(1,..) m.set(2,..) m.set(3,..)
m.del(2)           → 键 2 清 0
m.has(3)           → false   ← 错！数据还在，但扫到键 2 的空位就停了
m.get(3)           → 0       ← 同上
```

**数据没丢，但找不到** —— 这是最危险的一类 bug：不崩、不报错，静默错。

这正是 `std/kv` 注释里写的"边遍历边删会破坏探测链"。

### stage-0 用墓碑，但 qlmc 没有那个空间

stage-0 的 `__map_del` 把状态槽写成 **2**（墓碑），探测链继续有效。
但它的布局是每槽 3 字（state + key + val），qlmc 是 2 字（key + val）——
**没有墓碑位**。

加状态字会牵动 `_map_slot_of` / `_map_put` / `_map_grow` / `for k in map`
全部路径，风险远大于收益。

### 采用的做法：删完重建后半段

删掉一个槽之后，把**该槽之后连续的非空槽逐个摘下来重新插入**。
搬完之后探测链重新连续，语义与墓碑等价。

代价是删除变成 O(后段长度)，但 `std/kv` / `std/set` 的 `del` 都不在热路径上
（都是 `_clear` 的收尾）。

**实现细节**：`_map_put` 内部会 `count + 1`，而重建过程不该改变 count ——
每次插入后立刻 `count - 1` 抵消，最后再统一减一次。

### 返回值：照抄 stage-0 的 0

stage-0 的 `__map_del` 命中路径末尾也是 `ret 0`（它的文档没写返回值语义）。
qlmc 第一版返回 1（更合理），但差分对不上。

**改成同口径**：能不能差分比"返回值更合理"重要 —— 语言行为不该单方面偏离基准。

## 测试

`tests/t199_qlmc_mapiter.qma`，加进 `tests/qlmc_test.py` 的 `CASES`
作为**差分用例**（`s33_mapiter`），15 行输出与 stage-0 逐字节一致。

覆盖：int 键求和/计数、str 键、空 map、`continue`、`del` 命中/未命中、
del 后遍历跳过空槽、`has` 与 `del` 一致、del 后可重新 `set`。

**关键断言 `has3=1`**：删掉键 2 之后键 3 必须仍然找得到。第一版这里返回
`false`，正是上面那个探测链 bug。

### 顺带发现：stage-0 不支持 `map.len()`

```
[qlm] 编译错误：map 未知方法 .len（支持 set/get/has/del）
```

qlmc 支持它（`_vec_field(fc, hp, 8)`）。为了能差分，测试里改用遍历计数
代替 `len()` —— **方向是"qlmc 比 stage-0 强，不为能差分把它弄坏"**
（同 §7.41 的口径）。

## 覆盖率

`std/` **56 → 58**：`std/kv.qma` 与 `std/set.qma` 解锁。
`BASELINE` 已上调到 58。

剩余 12 个模块：

```
2  缺内建: xmm_load           (std/aes, std/tls13)
2  未知类型 TlsClientResult   (std/httpc_net, std/tls_net)
1  缺内建: args               (std/cli)
1  vec[vec[T]] §7.18          (std/csv)
1  泛型 [T: Ord]              (std/gen)
1  函数重复定义 _fail         (std/http)
1  函数重复定义 _get          (std/logfile)
1  缺内建: syscall            (std/park_linux)
1  结构体字面量含方法调用      (std/session)
1  缺内建: xmm_mov            (std/tls_client)
```

## 自举

30/30 组等价 + 不动点成立。stage-2 产物 638464 B，仍在 `ARENA_CAP = 4 MB`
余量内。
