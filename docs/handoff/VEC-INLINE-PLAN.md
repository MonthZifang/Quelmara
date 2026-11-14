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

#### 第 7 轮动手勘察的确切落点（解析层已试制验证过，降级未做完即回退）

**解析层已验证可行**（试制后自举不动点 + 既有夹具全过，随后按"不留半成品"纪律回退）：
`TY_REF=0x40000` + `RTYPES_BASE=VTYPES_BASE+1+VTYPES_MAX`、`TBL_SIZE` 顺延、
`_rtypes_add/_rtypes_base` 照抄 vec、`_type` 开头加 `P_AMP` 分支、`_ty_is_agg` 加
引用=标量、`_ty_size` 在 SLICE/ARRAY 分支**前**加引用=8。stt 用 `TBL_SIZE` 开（~21561）
自动扩容。**这套照抄即可，别再重新设计。**

**降级的三个落点 + 一个前置机制**（这是没做完的部分，下一版从这里接）：
1. **读穿透**：`_lower_expr` 的 `E_VAR` 分支（~6164，`let ty=fc.vty.get(v)` 后）——
   引用类型则 `_rtypes_base` 取 base，`OP_LOADD d, v, 0, 0` 解引用返回。
2. **写穿透**：`_lower_stmt` 的 `S_ASSIGN`（~7269）——目标为引用则
   `tmp=_lower_expr(rhs)` 后 `OP_STORE 0, d, tmp, 8`，不走 `_lower_into`。
3. **调用传址**：`_lower_expr` 的 `E_CALL` 实参循环（~6385 `vals.push(_lower_expr(...))`）——
   该形参是引用则对**变量实参**取址 `OP_ADDRV addr,0,0,-vloc-1` 传入；非变量实参先 fail-fast。
4. **前置机制 `_pin_slot`（关键，先做）**：取址要求实参变量**住在内存**。`_pin` 不保证
   栈槽（`_new_var` 在 `n<N_VARREG` 时仍给寄存器）。需给 FnCtx 加"可寻址"标记，
   `_alloc_vars` 对标记变量**强制帧槽**（跳过 callee-saved），否则 `ADDRV` 拿到寄存器
   编号当地址 = 静默错编。**这是 &T 的第一个独立可验证子步**（先让"被取址变量落栈槽"
   对既有代码零影响，再接 1/2/3）。

**顺序**：先 `_pin_slot`（可寻址变量落栈槽，差分验证既有代码不变）→ 解析层（照抄上面）
→ 读/写/传址三落点 → `&int` 差分 → `pin_cross_grow`。**每步不动点 + 差分，禁一次性铺开。**

#### 第 8 轮进度（工作区有未提交 &T 半成品，接续时先 `git diff` 看现状）

**qlmc 侧 &T 已实现并验证**（`bootstrap/qlmc/qlmc.qma`，未提交）：解析层 + 读穿透
（E_VAR）+ 写穿透（S_ASSIGN）+ 调用传址（E_CALL 实参循环，含"寄存器变量强制落帧槽"
`fc.vloc.set(v,-(_st_slot(fc))-1)`）。**实测**：`&int` 自增/乘加、循环内 bump、双引用
swap 全部正确；自举不动点 cand2==cand3（785408B）、既有夹具零回退。

**stage-0 C 后端（`tools/stage0/qlm.py` Codegen）也已加 &T**（未提交、未测）：
parse_type `&`→("ref",base)、ctype→`T*`、env_type→"ref:"、name 读 `*p`、assign 写
`*p=`、call 传 `&x`。**但差分夹具走 `--target win` = 原生后端 `qlm_native.py`，不走
C Codegen**——所以 C 后端这套对差分无用，真正要补的是 `qlm_native.py`。

**`qlm_native.py` 待补（下一版主战场，13588 行，IR 发射模型）**：
- 类型标记：仿 `_mark_vec/_mark_struct` 加 `fn.refv`（vreg→base）；`lower_fn`（~6498
  的形参标记循环）给 ref 形参打标。
- 读穿透：`eval` 的 `name`（~1612 `return env[e[1]]`）——ref 则 `fn.emit("load",d,v,("imm",0))`。
- 写穿透：`assign`（~5605）——ref 目标 `fn.emit("store",cur,("imm",0),spec)`，不走 mov。
- 传址：`lower_call`（~3041）用户函数实参处——ref 形参传实参变量地址；**取址需变量
  落帧槽**（同 qlmc 的 `_pin_slot` 坑，原生后端变量也是寄存器/帧槽分配，先找它的
  聚合按址传参机制复用）。
- `type_words` 对 ("ref",_) 返回 1（现已默认 1，核对即可）。
**验证**：`&int` 差分（stage-0 win vs qlmc）→ 既有 42/42 → 76/76 → 冷自举 → 提交 v4.120。

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

### 第 10 轮勘察：现行布局 / grow 机制的确切地图（&T 已就绪后重勘）

**现行布局**（`_lower_vecnew` ~15501）：句柄 `h` = 指向 **24B 固定头**
`[data_ptr@0, len@8, cap@16]`，数据是**另一块** `RT_ALLOC(cap*stride)`。
`vec.get(i)` = 读 `[h+0]` 得 data_ptr，再读 `[data_ptr+i*stride]` —— **双重访存**。
`_vec_field`（~15340）是 `ADDRF h,off + LOAD` 的 15 条窄缓存。

**grow 为何今天在值语义下成立**（`_vec_grow_body` ~15445）：只换**数据块**，
`memcpy` 后写 `[hp+0]=新data_ptr`。**头是固定的、所有别名共享同一头**，故 grow
对全部别名可见。这正是内联布局做不到的点。

**内联布局的死结（第 10 次确认）**：`[len,cap,data…]` 一块，grow 必须**整块重分配**，
句柄（指向旧块）随即失效，值语义的所有别名全断。**唯一解 = 引用语义**：grow 经
`&T` 穿透改写调用方句柄。v4.120 的 `&T` 已备好这块积木。

**b28 热路径不 grow**：`new(n*n)` 即满容量，push 恰 n*n 次不触发 grow，热循环纯
get/set——内联布局对它是纯收益。但布局改动是**全局**的，不能只给不 grow 的 vec 用。

**实施路径（&T 就绪后）**：vec 句柄要变成"指向可被 grow 改写的槽"的引用。两条路：
(a) 用户侧 vec 传参改 `&vec[T]`（基准需同步，语义=原地改，与 C 传指针一致）；
(b) 编译器内部把 vec 别名统一穿 `&T`，grow 穿透回写。先做 (a) 的最小复现
（`pin_cross_grow` 改引用传参）验证 grow 回传，再铺开到 get/set/push/len 全量。
**仍按步骤 4 门槛：每步 pin_cross_grow + 差分 + 不动点，禁一次性铺开。**

## 3. 三条编译器内部事实（地图，来自 9 次复盘）
- `_pin` **不保证**栈槽：`_new_var` 在 `n < N_VARREG` 时仍分配寄存器。
- `ADDRV` 立即数语义 = `-loc-1`。
- DCE 判死依据 = use 计数；grow 回传 MOV 被它删，必须走 STORE+ADDRV。

## 4. 排期建议
- 这是数周级工程（语言特性 + 编译器 + 自举验证），**不在单版本内强冲**。
- 建议独立大任务：先步骤 1（&T 语言层，可独立验证语法/小例子），再步骤 2–4。
- 未实现 &T 前，不要再次尝试 vec 内联布局——9 次失败已证明值语义下无解。
