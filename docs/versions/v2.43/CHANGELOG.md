# v2.43 — `map` 自动扩容（布局改 `[cap][len][data]`），§7.27 关闭

- 日期：2026-10-25
- 任务：把 §7.27 挂了两版的"qlmc 的 map 不扩容"修掉
- 影响面：自举层（map 的四个入口 + 新增 `_map_grow`/`_map_put`）/ 测试 / 文档

## 结果

```quelmara
let m = map[int]int.new(2)
let mut i = 1
while i <= 17 { m.set(i, i); i = i + 1 }   // 2 → 4 → 8 → 16 → 32
// 17 个键全部取回，1+…+17 = 153
```

新夹具 `tests/selfhost/s23_map_grow.qma` 与 stage-0 **逐字节相同**：
扩容、扩容后覆盖、扩容后继续插入、命中/未命中、两张表各自扩容、17 键大扩容，全过。

## 分两步做（v2.41 一次改五处的教训）

v2.41 直接上"扩容"，结果连不扩容的基础用例都段错误，只好整段回退。这次拆开：

| 步 | 改什么 | 单独验证 |
|---|---|---|
| 1 | **只改布局**：头 24 字节 `[cap][len][data]`，键值对搬到独立块；`_map_base` 从 `h+16` 变成 `[h+16]`；`_map_new` 分配 24 + `cap*16`；`_map_slot_of` 满时返回 0（不再 `exit`） | `map.new(4)` + 2 键与 stage-0 逐字节相同 |
| 2 | **加 `_map_grow`**：容量翻倍 + `OP_MEMCPYN` 拷旧数据 + `OP_ZERON` 清零新槽位 + 更新 `[h+0]`/`[h+16]` | 9 键用例与 stage-0 逐字节相同 |

布局这一步是必须的：只有数据在独立块里，"扩容"才可能只是**换指针**，
调用方手里的句柄（可能已经钉进了好几个帧槽）一个字节都不用动。

`_map_grow` 里两个细节：

- **新槽位必须清零**。qlmc 用"键 == 0"当空槽标记，不清零的新块里键是随机的，
  会被当成命中，读出一个不存在的值。`OP_ZERON` 的字节数用运行期值（`cap*16`）。
- **`OP_MEMCPYN` 的参数序是 `(字节数, 目的, 源)`**，跟 `OP_STORE` 的 `(addr, 值, 宽度)`
  不一样，容易写反。写反的表现是往旧块里拷新块的内容。

## 这轮的真凶：条件重赋值 + 跨 join 使用

第一步做完好好的，加上扩容就段错误（`mg.qma`，9 个键）。`fault_probe.py` 抓到
RVA 0x1E31、AV 地址 0、`R14=0`，看着像"`_map_slot_of` 返回 0 之后没扩容就往下走了"。
把整个 `.text` 线性反汇编（capstone）对着 RVA 一看，`_map_set` 里的 grow 分支
**在**（`cmp rax,0 / jne 0x1de6`），问题是 `jne` 跳过去之后读的是 `[rbp-0x98]`，
而那个帧槽在"没扩容"这条路上还是 0 —— 于是 `mov r8,[rax]` 读地址 0。

根因是源码里这个形状：

```quelmara
let mut slot = _map_slot_of(fc, hp, kp)
if slot == 0 { _map_grow(fc, hp); slot = _map_slot_of(fc, hp, kp) }
... 用 slot ...
```

qlmc 的分配器把两次定义当成**同一个变量的前后两个定义**（`let` 那条 `MOV dst, t`
被 coalesce 掉），于是每个使用点按"线性顺序上最近的那个定义"定位置 —— 跳过 if
的那条路上，最近的定义根本没执行。

修法：**别跨 join 重赋值**，两条路各写一次、各用一个只定义一次的变量：

```quelmara
let s1 = _map_slot_of(fc, hp, kp)
if s1 != 0 { _map_put(fc, s1, kp, vp, hp); jmp 结束 }
_map_grow(fc, hp)
let s2 = _map_slot_of(fc, hp, kp)
_map_put(fc, s2, kp, vp, hp)
结束:
```

`_map_put` 抽成独立函数（`slot`/`kp`/`vp` 都是形参，各只定义一次）。
`_map_slot_of` 自己内部也有同样的形状（`lfull` 里 `slot = 0`），但它用的是 `_pin`
出来的变量（固定帧槽），所以一直没事 —— 这也解释了为什么这个坑到 v2.43 才炸。

已进坑表 **#45**。

## 还剩两个已知分歧（都不影响现有夹具）

| 分歧 | qlmc | stage-0 |
|---|---|---|
| 键 `0` | 存不进去（"键 == 0"是空槽标记） | 正常（有独立 `state` 数组：0 空 / 1 占用 / 2 墓碑） |
| `map.new(0)` / `map.new(3)` | 照收（内部原样翻倍） | 编译期报错"容量必须是 2 的幂" |

两个都要动数据结构或加运行期检查，留作后续（§7.27 末尾记了修法方向）。

## 另外：§7.24「`-jN` 编自己崩」已不复现

顺手复测了一下多线程编自己：

```bash
./build/qlmc.exe build bootstrap/qlmc/qlmc.qma -o /tmp/tj4.exe -j 4   # rc=0
```

`-j 1 / 2 / 4 / 8` 四种取值都是 rc=0、产物 **492 544 字节且 md5 相同**（`3457fd35…`）。
v2.35 记的现场（读 `0xFFFF…FFFF`、RIP 在 DLL 里）不再出现。最可能的真凶是那两版做的
两件事：堆上限 32 → 64 MB、`ARENA_CAP` 16 → 4 MB（多线程下**每线程一份 arena**
才是真正吃满堆的地方）。

顺带记一个**用法坑**：`-j` 和数字**必须用空格分开**。写成 `-j4` 会被当成普通实参
忽略，然后走"自动"路径，横幅还照样打 `-j4` —— 看起来像"设了 -j1 却还是 -j4"。
（我自己就先被这个骗了一轮。）

## 另外发现一个 stage-0 的缺陷（§7.28）

`len(map)` 在两种场景下会读到垃圾（落到 `str_len` 读 `[m-8]`）：同一函数里有两张
map、或同一文件里另有一个带 map 的函数。qlmc 侧两种场景都对。归 stage-0 那条线，
`tests/selfhost/s23_map_grow.qma` 里因此**不在扩容之后查 `len()`**。

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/qlmc_test.py` | **PASS=57**（27 组用例 + 并行确定性 2 条；新增 `s23_map_grow`） |
| `python tests/bootstrap_test.py --strict` | **五级全 PASS**（stage-2 25/25 组等价，不动点仍成立，492 544 字节） |
| `python tests/run_win_tests.py` | **PASS=290 FAIL=0 SKIP=1** |
| 四道门 | 全绿 |

## 体积与耗时

| 项 | v2.42 | v2.43 |
|---|---|---|
| `bootstrap/qlmc/qlmc.qma` | 296 KB | 296 KB（303 319 B） |
| `build/qlmc.exe` | 2 028 KB | 2 030 KB（2 079 232 B） |
| stage-2（qlmc 编自己） | — | 492 544 B |
| 自己编自己（`-j 4`，进程内 min of 3） | — | 308–325 ms（后端 61–67 ms） |

源码从 231 KB（v2.38 口径）涨到 296 KB，**耗时不能跨版本直接比**。

## 改动

| 文件 | 改了什么 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | 新增 `_map_grow` / `_map_put`；`_map_base` 改成读 `[h+16]`；`_map_new` 改成 24 字节头 + 独立数据块；`_map_slot_of` 满时返回 0；`_map_set` 走"扩容后重找" |
| `tests/selfhost/s23_map_grow.qma` | **新增**：7 个只被调用一次的检查函数（扩容求和 / 覆盖 / 继续插入 / 命中 / 两张表 / 17 键 / 不扩容时 len） |
| `tests/qlmc_test.py` | 用例 26 → 27 |
| `docs/05-toolchain.md` | 坑表 **#45**（条件重赋值 + 跨 join） |
| `docs/07-gaps.md` | §7.27 改「已修（v2.43）」+ 分两步做法 + 两个残留分歧；**新增 §7.28**（stage-0 的 `len(map)` 类型推断不稳） |
| `docs/06-status.md` | §3.25 表加 `s22_f64print` / `s23_map_grow` 两行，自举状态更新到 v2.43 |

## map 现状

- ✅ `new` / `set` / `get` / `has` / `len`、**自动扩容**、两张表互不干扰、函数内建表
- ❌ 键 `0`、`str` 键按内容比较（qlmc 比的是指针）、`del`、扩容策略（qlmc 满才翻倍，
  stage-0 是 70% 负载就翻倍）
