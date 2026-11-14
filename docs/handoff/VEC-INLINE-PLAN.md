# vec 内联布局重启方案（前置：&T 引用语义）

> 交接文档。性能根因、失败复盘、实测数字见 [`../perf/ANALYSIS.md`](../perf/ANALYSIS.md)
> 与 [`PERF-ROADMAP.md`](PERF-ROADMAP.md)；本文件只给**可执行步骤 + 验证门槛**，不重复数字。

## 0. 为什么必须做这件事

`bench/speed` 里 quelmara 列在数组密集型基准上仍显著慢于 C（倍数见 `06-status.md` §7
与 `versions/v4.78/CHANGELOG.md`）。唯一结构性根治杠杆是 **vec 内联布局**
（`[len][cap][data…]` 取代句柄 + 堆块），把 `vec.get(i)` 从 6 指令降到接近 C 的 1 条。
其余调参（关越界检查、bounds_check 公平性）已落地（v4.78），收益有限且只在部分基准有效。

## 1. 死结定性（9 次尝试的终判）

qlmc 是**值语义 + 标量不可寻址**。vec 内联后，`grow` 换块必须让"同一 vec 的所有别名看到
新块地址"——值语义下无法表达：

| 方案 | pin_cross_grow 复现器 | 结论 |
|---|---|---|
| 双 vreg MOV 回传 | 挂 | DCE 删 MOV |
| STORE + ADDRV 回传（9a） | **跑通（余 imm 错）** | 方向对，ADDRV imm 错 |
| 槽降级 + ADDRV（9b） | 仍挂 | 降级引入新错 |

**重启条件 = 实现 `&T` 引用语义**（形参/返回值可按引用传 vec，而非值拷贝）。
实现后可复用 9a 的 STORE+ADDRV 回传方向，只需修 ADDRV imm 与槽降级的 DCE 交互。

## 2. 落地顺序（建议）

### 步骤 1：语言层实现 `&T` / `box` 引用类型
- 语法：新增 `&T` 形参/返回，使 vec 以引用传入而非值拷贝。
- 同步：parser、类型推断、QuIR 增加"引用"种类、IR 发射器支持"按地址 load/store"。
- 这同时解锁"多层别名每层间接 + 穿透"——正是 grow 句柄传播的本质需求。
- 风险：语言特性改动，需保证 `bootstrap/qlmc` 自举不破（见步骤 4 验证门槛）。

#### 步骤 1 的具体编码方案（第 6 轮勘察定稿，务必照此避坑）

**类型码不能直接打包 base**：现有码是紧凑区间（STRUCT=0x1000 / VEC=0x8000 /
MAP=0x10000 / SLICE=0x20000 / FN=0x30000 / ARRAY=0x100000+(len<<8)+elem），
`TY_REF + base` 在 base 本身是 vec/array 时会进位撞区间（同 v3.65 之前的
`vec[vec[str]]` 事故）。**照抄 vec 的类型表方案**：
- 新增 `TY_REF = 0x40000`（落在 FN=0x30000 与 ARRAY=0x100000 之间的空档），
  编码 `TY_REF + ti`，`ti < RTYPES_MAX(=2048)` → 永远在 [0x40000,0x40800)，不撞区间。
- 新增引用类型表 `stt[RTYPES_BASE..]`（仿 `VTYPES_BASE`，`_rtypes_add/_rtypes_elem`
  照抄 `_vtypes_add/_vtypes_elem`），`TBL_SIZE` 相应加大。
- `_type`（qlmc.qma ~1134）开头加 `&` 分支：`_adv` 后 `_type` 解析 base，
  `_rtypes_add` 登记，返回 `TY_REF+ti`。

**必须同步改的判定点**（漏一个就静默错分类）：
- `_ty_is_agg`：引用是 8 字节标量指针 → 加 `if ty>=TY_REF && ty<TY_REF+RTYPES_MAX return false`。
- `_ty_size`：引用返回 8，**必须在 `>=TY_SLICE && <TY_ARRAY` 那条之前判**
  （否则 0x40000 落进 [SLICE,ARRAY) 被当成 16 字节）。
- 全文 `>= TY_x && < TY_y` 区间判断（~15 处，grep 可列）逐一核对 TY_REF 不被误吞。

**降级**：`&T` 形参 = 传地址（调用方 `ADDRV`/取址，被调方形参拿到地址）；
被调内对 `&T` 变量的读 = `LOAD [addr]`、写 = `STORE [addr]`（穿透）。
第一批只做 `&int`/`&vec[T]` 形参 + 读写穿透，返回引用/多层别名留后。

**验证**：先 `&int` 小例（`fn inc(x:&int){x=x+1}` 调用后实参 +1）stage-0/qlmc 差分；
再 `pin_cross_grow` 复现器；每步自举不动点。**禁止一次性把降级全铺开**。

### 步骤 2：编译器层复用 9a 的 STORE+ADDRV 回传
- 方向已验证（复现器从"挂起"变"跑完"），余错仅在 `ADDRV` 立即数（`-loc-1` 语义）
  与 DCE/降级的相交。
- 新增 `_pin_slot`（强制 `vloc=-(u+1)`）让 `hp`/`h` 落栈槽，grow 后穿透改写。

### 步骤 3：同步 7 处（历史清单，务必逐一核对）
1. `_vec_field` 内联（off=0 返回 `h+16`，仅对 stride==8 的 vec）
2. `JCMPVLEN disp=0`
3. `_lower_vecnew` 单块
4. push 不 pin（**错**——见 ROADMAP 勘误）
5. push len `[h+0]`
6. grow 双写（**也错**——被 DCE 删）
7. `map.len` 换 `_map_count`；map 的 `[h+0]` 是 cap / vec 的 `[h+0]` 是 data（语义相反，勿混）

### 步骤 4：验证门槛（防第 10 次回退）
- **先过 `tests/rt/pin_cross_grow.qma`**（秒级复现器），再跑 `bootstrap_test` 全绿。
- 每个 IR 改动带**差分验证**（历史教训：没有差分验证不算修好）。
- 禁止一次性大改：每改一处跑一次 `pin_cross_grow` + 最小 RT 网。

### 步骤 5：预期收益（倍数列见 `06-status.md`）
- 数组密集型基准整体下移（`b31`/`b28`/`b22`/`b23`/`b26` 等），是"跑赢 go/c 45+"唯一
  可行的结构性杠杆。

## 3. 三条编译器内部事实（地图，来自 9 次复盘）
- `_pin` **不保证**栈槽：`_new_var` 在 `n < N_VARREG` 时仍分配寄存器。
- `ADDRV` 立即数语义 = `-loc-1`。
- DCE 判死依据 = use 计数；grow 回传 MOV 被它删，必须走 STORE+ADDRV。

## 4. 排期建议
- 这是数周级工程（语言特性 + 编译器 + 自举验证），**不在单版本内强冲**。
- 建议独立大任务：先步骤 1（&T 语言层，可独立验证语法/小例子），再步骤 2–4。
- 未实现 &T 前，不要再次尝试 vec 内联布局——9 次失败已证明值语义下无解。
