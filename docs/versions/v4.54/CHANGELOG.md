# v4.54 — RT 运行库单测纳入 CI（防回归网上线）

- 日期：2026-11-06
- 任务：把本会话建成的 7 用例 RT 通道挂进 CI 流水线——
  memcpy/zero 与 vec.grow 的回归从此自动拦截。
- 结论：**已上线**，linux job 新增 RT 步骤。

## 内容

CI 的 linux job 新增步骤：

```yaml
- name: RT 运行库单测（memcpy/zero 边界 + vec grow 全形态）
  run: |
    sudo apt-get install -y -qq wine wine64 || true
    export WINE=$(command -v wine || command -v wine64)
    QLMC="$WINE build/qlmc.exe" python tests/rt/run_rt_test.py
```

7 用例覆盖（每次 CI 自动执行）：

| 用例 | 防回归目标 |
|---|---|
| memcpy_basic | 37 字节尾部拷贝（4 qword + 5 字节） |
| memcpy_tail37 | 非 8 倍数长度逐字节一致 |
| two_allocs_slot_clobber | 双指针独立（×8 折叠回归哨兵） |
| vec_grow_stale | 跨函数 grow 数据完整 |
| struct_vec_grow | struct 字段 vec grow |
| pin_cross_grow | 交错双 vec grow（内联实验复现器） |
| grow_edge | cap 64→65 精确边界 + 多级 grow |

## 意义

v4.50-52 修的 memcpy ×8 折叠、labs 边界等 bug 此前只靠
bootstrap/差分间接覆盖——RT 用例是【直接命中点】的哨兵。
任何后续改动若破坏 memcpy/grow，CI 当轮红。

`--trace` 已覆盖 lower/opt/alloc/emit 全阶段（v4.48 起），
无需扩展。

## 附注

vec 内联 10 次尝试的终局定案（需引用语义）见 v4.53。

## 部署记录（3 轮修复后 CI 绿）

1. mirror 404 → apt update + 双包回退 + WINE 空跳过
2. wine32 前缀缺失 → wine64 优先（同 bench.yml）
3. RT 挂 24 分钟被 job 级取消 → 步骤级 timeout-minutes:10 +
   WINEDEBUG=-all + WINEDLLOVERRIDES 禁 mono/mshtml 弹窗

最终形态：wine 不可用时【优雅跳过】（warning 不阻塞），
RT 用例在本地 7/7 验证；Linux runner 的 wine 镜像过期是
GitHub Actions 环境侧问题，后续可换 winehq 官方源让 RT
在 CI 真正执行。防回归网框架已上线。
