# v4.55 — winehq 官方源接入：RT 用例在 CI 真执行

- 日期：2026-11-06
- 任务：v4.54 的 RT 用例在 Linux runner 因 Ubuntu mirror 快照过期
  （wine 404）只能优雅跳过——防回归网没真正上线。
- 结论：**接入 winehq jammy 官方源**，RT 7 用例将每轮 CI 真执行。

## 改动

CI 的 RT 步骤前接入 winehq 官方仓库：

```
dl.winehq.org/wine-builds/ubuntu/dists/jammy/Release.key → keyrings
dl.winehq.org/wine-builds/ubuntu/dists/jammy/winehq-jammy.sources
apt install winehq-stable（回退 wine64）
```

Ubuntu mirror 的 libsoup 404 不再影响 wine 安装。

## 验证

CI 提交后观察 RT 步骤输出：应从"wine 不可用，跳过"变为
"RT 单测：7/7 通过"。

## 附注

winehq 源装出的 wine 与本地版本可能不同——RT 用例全部是
确定性断言（无时序），跨 wine 版本稳定。
