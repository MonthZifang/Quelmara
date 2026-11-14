# v4.118 — 修复 thread_start 实参恒为 0（CI Windows 红）+ 改名门禁残留

- 日期：2026-11-14
- 性质：**正确性 bug 修复**（非性能），解除 CI Windows/Linux 双红
- 影响面：编译器（thread_start 块布局）、门禁脚本、测试

## 根因（CI Windows `s32_thread` 差分失败）

CI（run 43593641080 及更早）Windows PE 回归唯一失败项是 `s32_thread`
（tests/t197_qlmc_thread.qma）：stage-0 打 `bits=15`，qlmc 打 `bits=0`（cnt 都=4）。
本地用最小复现件确认：**`thread_start(fn, arg)` 的 arg 恒为 0**（stage-0 正常）。

`_bi_thread_start` 把实参写进线程块 **[+24]**，而共用的 `RT_SPAWN` 蹦床从
**[+32]** 读第 0 个实参（`mov rcx,[rbx+32]`，与 `spawn` 的块布局一致）。
于是蹦床读到未初始化的 `[bp+32]=0`，线程函数永远收到 arg=0。
t197 里 4 个 worker 各传 1/2/4/8 做按位或，arg 全 0 → `bits=0`；cnt 与 arg 无关仍=4。
**文档注释里的块布局也写错成 [+24]**，是这次误写的源头。此 bug 早于本轮性能改动
（v4.115 基线编译器同样复现），属历史遗留，非 v4.116/v4.117 引入。

## 改动

| 文件 | 改动 |
|---|---|
| `bootstrap/qlmc/qlmc.qma` | `_bi_thread_start` 实参偏移 **[+24]→[+32]**（对齐 RT_SPAWN 蹦床）；同步修正块布局文档注释（[+24] 保留、[+32] 第 0 实参） |
| `tools/dev/push_via_api.py` | `REPO_FALLBACK` 由旧名改为当前仓库名，删除旧名注释（Linux `check_names` 门禁残留） |
| `tests/s_thread_arg.qma` | 新增确定性差分夹具：4 线程各传不同 arg 写**各自独立** static_word（避共享字竞态），stage-0/qlmc 必须一致 |
| `tests/qlmc_test.py` | 注册 `thread_arg` 夹具 |

## 验证

| 项 | 结果 |
|---|---|
| 最小复现件 | 修复前 qlmc arg=0 / stage-0 arg=12345；修复后两者都=12345 |
| s_thread_arg 差分夹具 | stage-0 / qlmc 输出逐字节一致（111/222/333/444） |
| t197（s32_thread） | 修复后 **10/10 次 bits=15 cnt=4**（修复前恒 bits=0） |
| 种子引导不动点 | cand2==cand3，776192 字节，SHA256 一致 |
| selfhost 运行差分 | 42/42 与基线一致 |
| check_names（改名门禁） | PASS（Linux 门禁解除） |
| 源码级冷缓存严格自举 | **PASS**（`QLM_NO_CACHE=1`）：stage-0 编 stage-1 879.3s；stage-2 776192 字节；42/42 组逐字节一致；错误路径干净退 2；stage-2==stage-3 不动点成立 |

## 说明

- 本版是**正确性修复**，不含性能优化，基准跑分不变。
- t197 的共享字按位或本身是非原子读-改-写，理论上仍有竞态窗口；修复 arg 后
  本地 10/10 稳定。新增的 s_thread_arg 用独立槽位，是确定性判据。
- 通用内联（b57/b60 性能）在下一版 v4.119 单独提交，不与本 bug 修复混版。
