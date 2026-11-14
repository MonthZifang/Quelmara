# v4.120 — `&T` 引用语义（vec 内联布局的前置语言特性）

- 日期：2026-11-14
- 任务：实现 `&T` 引用形参——传地址、读写穿透到调用方变量。这是 **vec 内联布局**
  （b28/b59/b23/b22/b49 一整片数组密集基准的结构性根治）的必经前置：值语义下
  grow 换块无法让别名看到新地址，9 次尝试已证明无解（见 `handoff/VEC-INLINE-PLAN.md`）。
- 影响面：语言特性（qlmc + stage-0 原生/C 双后端）、测试。**本版不直接改基准跑分**，
  为下一版 vec 内联布局铺路。

## 改动

| 文件 | 改动 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | `TY_REF=0x40000` 类型表模型（`RTYPES_BASE`/`_rtypes_add/_rtypes_base`）；`_type` 加 `&` 分支；`_ty_is_agg`/`_ty_size` 认引用为 8 字节标量；`E_VAR` 读解引用、`S_ASSIGN` 写穿透、`E_CALL` 实参取址（寄存器变量强制落帧槽） |
| `tools/stage0/qlm_native.py` | `fn.refv`/`fn.force_mem`；分配器对 force_mem 直接落帧槽；新 IR 码 `addrslot`（`lea [rbp-off]`）；`lower_fn` ref 形参打标+禁内联；`eval name` 解引用、`assign` 穿透、`lower_call` 传址 |
| `tools/stage0/qlm_opt.py` | `addrslot` 登记 `vreg_mentions`/`PURE` |
| `tools/stage0/qlm.py` | C 交叉验证后端：`&T`→`T*`，读 `*p`/写 `*p=`/调用传 `&x` |
| `tests/s_ref.qma` + `tests/qlmc_test.py` | 引用差分夹具（inc/addmul/循环 bump/双引用 swap）并注册 |
| `bootstrap/parser/qlm_parse.qma` + `tools/dev/astdecl.py` | 声明级 parser 与 oracle 认 `&T`（渲染 `&base`）——首推 CI 的 parsediff 对拍曾因此红，补齐后通过 |

## 关键机制与坑

- **类型码不打包 base**：`TY_REF+base` 在 base 是 vec/array 时进位撞区间（v3.65
  `vec[vec[str]]` 事故那类）。照抄 vec 类型表：`TY_REF+ti`，`ti<2048` 永落
  `[0x40000,0x40800)`，~15 处区间判断不用改。
- **取址必须落帧槽**：寄存器没有稳定地址。qlmc 在传址点把实参变量
  `vloc` 强制改帧槽（IR 符号化、发射期才解析位置，故对该变量所有读写一致生效）；
  stage-0 原生后端用 `force_mem` 集合让线性扫描分配器直接落槽 + `addrslot` 取址。
- **引用函数禁内联**：引用语义依赖独立栈帧与 force_mem，内联传播复杂，先禁。
- **读/写穿透**：引用变量 vreg 住的是地址——读 `LOAD [v]`、写 `STORE [v]=rhs`，
  不是改 vreg 本身（那是改地址）。

## 验证

| 项 | 结果 |
|---|---|
| 引用差分夹具 s_ref | stage-0(win) / qlmc(win) 逐字节一致（6 7 22 101 22 10 8 3 10） |
| 全套 qlmc_test | **PASS=126 FAIL=0**（含 selfhost 42、并行确定性 -j1==-j4、新 ref 夹具） |
| 自举对拍四件套 | lexdiff 388/0、parsediff 292/0、irdiff 127/0（s_ref 在 A64 跳过，同其他 x86-only 特性）、emitdiff 10/0 |
| 种子引导不动点 | cand2==cand3，785408 字节，SHA256 一致 |
| 全量 76 项 ×3 轮 | **76/76 与 C 校验一致**；b68/b28/b57 等基准产物与 v4.119 **逐字节相同**（语言特性不改既有代码）——几何平均读数 1.649 vs 1.637 纯属测量噪声 |
| 源码级冷缓存严格自举 | **PASS**（`QLM_NO_CACHE=1`）：stage-0 编 stage-1 861.9s；stage-2 785408 字节；42/42 组逐字节一致；错误路径干净退 2；stage-2==stage-3 不动点成立 |

## 已知边界 / 遗留

- 第一批只做 `&int` 形参 + 读写穿透；`&vec[T]`、返回引用、多层别名、引用复合赋值（`+=`）留后。
- 引用函数禁内联（性能中性偏保守）；force_mem 变量落帧槽（取址的必然代价）。
- **下一步**：用 `&T` 做 vec 内联布局（`[len][cap][data…]`），把 `vec.get` 从双重
  访存降到接近 C 的单条——见 `VEC-INLINE-PLAN.md` 步骤 2–4。
