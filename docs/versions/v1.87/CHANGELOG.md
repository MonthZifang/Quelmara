# v1.87 — FFI：`@ffi` 调用系统库（语言层红标 → 绿）

- 日期：2026-10-24
- 任务：把 `07-gaps.md` §1 里"FFI（自研后端）❌ 无动态链接器；`@extern` 只有 C 后端原型"
  一次补成绿——自研后端要能直接调系统库
- 影响面：语言 / 编译器（解析、降级、优化、PE 发射）/ 文档

## 改动

| 文件 | 改了什么 |
|---|---|
| `tools/stage0/qlm.py` | 注解参数改为**逗号分隔的字符串列表**（`@ffi("dll", "Sym")` 需要两个）；新增 `Parser._bind_ffi`——登记 `fdef["ffi"] = {dll, sym}` 并在解析期做类型白名单（`int/bool/f64/f32`，返回可 `void`）；`@extern` 与 `@ffi` 同时出现直接报错；C 后端把 `@ffi` 退化成普通 `extern` 原型 |
| `tools/stage0/qlm_native.py` | `Lower.ffi_decls` + `Lower.lower_ffi`：发 `('ffi', dst, dll, sym, kinds, ret, args)`，`kinds` 由**声明**决定（`"i"`/`"f64"`/`"f32"`）；整数实参按 C 口径自动 `cvtsi2sd`；`Lower.run` 加平台闸（非 Windows 直接报错）；新增内建 `cstr(s)` / `cstr_read(p)`；`allocate` 的 `call_sites` 与内联 `_map_ins` 登记 `ffi`；基类 `Codegen` 显式拦截（二道闸） |
| `tools/stage0/qlm_opt.py` | `vreg_mentions` / `_subst_vregs` / `_EFF` / `_LAT` / CSE 失效点登记 `ffi`（§4.1 清单五处齐） |
| `tools/stage0/qlm_pe.py` | `WinCodegen.gen_ffi`：Win64 布局（整数 `RCX/RDX/R8/R9`、浮点 `XMM0-3` 独立计数、第 5+ 个同类实参落 `[rsp+32+8k]`、恒留 32 字节 shadow space）；返回值 `RAX`/`XMM0`，`bool` 按 32 位零扩展；导入表从"白名单归组"扩成 `(dll, 符号)` 键，`build_idata` 支持任意 DLL |
| `tests/t120_ffi.qma` | 新增：int/void/bool/f64/f32、栈传参 5 参与 7 参、三个 DLL、`cstr`/`cstr_read` 往返、读自身 exe 验 `MZ` |
| `tests/bad/ffi_str_param.qma`、`ffi_struct_param.qma`、`ffi_body.qma` | 新增负向夹具（str 形参 / struct 形参 / 带函数体） |
| `tests/run_win_tests.py` | 新增 `test_ffi()`（6 项断言：自校验、导入表多 DLL、符号集合、ELF fail-fast）+ 3 条负向登记 |
| `bench/ffi_bench.qma` | 新增：调用开销（原生 vs FFI）、1 MiB 拷贝（`mem_copy` vs `RtlMoveMemory`）、串长度（`len` vs `lstrlenA`） |
| `docs/02-language.md` | 新增 §4.9（语法/类型表/Win64 口径/四条边界/证据）；§4.7 注解表加一行；§7 内建 67 → 69（`cstr`、`cstr_read`） |
| `docs/04-compiler.md` | 新增 §6.2.2 FFI 链路六段表 + 两个"不能省"的坑（搬移顺序、BOOL 零扩展）；§6.2 导入表口径改写 |
| `docs/07-gaps.md` | §1 FFI 行 ❌ → ✅ v1.87（边界：仅 Windows PE / 无变参 / 无按值结构体 / 无回调 thunk）；P2 第 3 项划掉 |
| `docs/06-status.md` | 回归行更新；新增 §3.4g FFI 开销与吞吐 |
| `tools/stage0/qlm_cli.py` | `VERSION` → `1.87.0`（收尾时并行轨已推进到 `1.91.0` 并建了 `v1.91/`，按门禁口径以最新目录为准，版本号由并行轨持有） |

## 验证

| 命令 | 结果 |
|---|---|
| `python tests/run_win_tests.py` | PASS=256 FAIL=4 SKIP=0（新增 9 项 FFI 断言全 PASS；4 个 FAIL 全在并行轨的 derive/覆盖率夹具，见下） |
| `python tests/lexdiff.py` | PASS=228 FAIL=0（232 个源文件，SKIP 4） |
| `python tests/parsediff.py` | PASS=148 FAIL=6（6 个 FAIL 全是并行轨新夹具；`t120_ffi` 两侧一致） |
| `python tests/irdiff.py` | PASS=88 FAIL=0 SKIP=68（`t120_ffi` 属预期 SKIP：非 Windows 目标构建期 fail-fast） |
| `python tests/emitdiff.py` | PASS=10 FAIL=0 |
| `python tools/dev/check_docs.py` | PASS（过期断言 / 索引 / 版本目录 / 数字单一来源 / 版本号同源） |
| `python tools/dev/check_names.py`、`check_origin.py` | PASS |
| `python tools/dev/gen_stdlib_doc.py --check` | PASS（58 个模块 / 385 个公开函数） |
| `python bench/ffi_bench.qma`（手跑 3 次） | 原生调用 2–3 ns / FFI 3–4 ns / 拷贝 7.6–7.8 GB/s / `lstrlenA` 1 MiB 119–141 µs |

## 已知边界 / 遗留

- **仅 Windows PE**：ELF 后端是静态 ET_EXEC（单 RWX `PT_LOAD`，无 `PT_INTERP`/`PT_DYNAMIC`），
  外部符号无处解析；`--target native` 下 `@ffi` 编译期 fail-fast 并给出这条原因。
  真要支持 Linux 得先有动态链接（`PT_INTERP` + `.dynamic` + PLT/GOT + 符号哈希），单开一版。
- **无变参**：`printf`/`wsprintfA` 需要 `AL` = 向量寄存器个数，未做。
- **无按值结构体**：Win64 的"≤8 字节按整数 / >8 字节按隐式指针"两套规则未做，形参限标量。
- **无回调 thunk**：Quelmara 函数用自研 ABI（`RDI RSI RDX RCX R8 R9`），与 Win64 不同；
  把函数地址直接传给 `EnumWindows` 这类 API 会被错位读参，需要编译器生成寄存器重排层。
- **符号错误是加载期错误**：DLL 名/符号名写错不会在编译期报，进程起不来
  （`0xC0000135` / `0xC0000139`）。没有做"符号存在性"静态校验（需要解析目标机的
  System32 DLL 导出表，属工具链工作）。
- **并行轨**：本版只改语言层；同一工作区里另有会话在改闭包 / Drop / doc comment / 派生（v1.86–v1.90）。
  两边文件面基本不重叠，但有两处需要合并时处理：
  1. 版本号：本版开工时并行轨的 `VERSION` 已到 `1.90.0`，为避免与 v1.86/v1.88/v1.89 冲突，
     本版取 **v1.87** 并短暂把 `VERSION` 设为 `1.87.0`；收尾时并行轨已推进到 `1.91.0` 并建了
     `v1.91/`，门禁按"最新目录"判定，版本号已由并行轨接管，本版不再持有——两边不要各留一半。
  2. `06-status.md` 里 4 个 FAIL / 6 个 parsediff FAIL 全部是并行轨夹具未同步（enum 派生、`f64` 字段派生、
     doc comment、宏、反射、覆盖率文案）。本版没有碰这些路径，数字按"HEAD + 本版改动"实测记录，
     并行轨收尾时按它自己的实测值覆盖。
