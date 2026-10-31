"""v3.45：`qlmc irdump` 工具的回归测试。

为什么要单独测一个"调试工具"：它是**查手写 IR 缺陷的唯一手段**，
自己坏了会让人误判成"目标函数的 IR 就是这样"。v3.44 的 `udp_sendto`
崩溃就是缺了它才耗掉 40 轮，所以这个工具必须可靠。

测什么：
  1. 清单模式（不给函数名）能列出所有函数 + IR 条数 + 帧字节；
  2. 单函数模式能打出完整 IR，且条数与清单一致；
  3. 不存在的函数名必须报错退出（不能静默返回空）；
  4. IR 里的寄存器/帧槽标注合法（`r<N>` / `s<N>` / `-`）；
  5. 6 参函数的 `PARAMSTK`（栈形参）必须出现 —— 这是手写 IR 最容易
     搞错的那类指令，工具要能看见它。
"""

import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QLMC = os.path.join(ROOT, "build", "qlmc.exe")

PASS = 0
FAIL = 0


def ok(msg):
    global PASS
    PASS += 1
    print(f"[PASS] {msg}")


def bad(msg):
    global FAIL
    FAIL += 1
    print(f"[FAIL] {msg}")


SRC = """fn f6(a: int, b: int, c: int, d: int, e: int, f: int) -> int {
    return a + b + c + d + e + f
}

fn main() {
    let r = f6(11, 22, 33, 44, 55, 66)
    print("sum=" + r.to_str())
}
"""


def main():
    if not os.path.exists(QLMC):
        print(f"[SKIP] 找不到 {QLMC}")
        return 2

    d = os.path.join(ROOT, "build")
    src = os.path.join(d, "_irdump_probe.qma")
    with open(src, "w", encoding="utf-8", newline="\n") as f:
        f.write(SRC)

    # 1) 清单模式
    r = subprocess.run([QLMC, "irdump", src], capture_output=True,
                       text=True, errors="replace", timeout=120)
    if r.returncode != 0:
        bad(f"清单模式失败 rc={r.returncode} {r.stderr[-300:]}")
        return 1
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("fn ")]
    if len(lines) == 2:
        ok(f"清单模式列出 2 个函数：{lines[0].strip()} | {lines[1].strip()}")
    else:
        bad(f"清单模式应列出 2 个函数，实得 {len(lines)}")

    m = re.search(r"fn f6\s+ir=(\d+)", r.stdout)
    if not m:
        bad("清单里找不到 f6 的 IR 条数")
        return 1
    f6_ir = int(m.group(1))
    if f6_ir > 0:
        ok(f"f6 的 IR 条数 = {f6_ir}")
    else:
        bad("f6 的 IR 条数为 0")

    # 2) 单函数模式
    r2 = subprocess.run([QLMC, "irdump", src, "f6"], capture_output=True,
                        text=True, errors="replace", timeout=120)
    if r2.returncode != 0:
        bad(f"单函数模式失败 rc={r2.returncode} {r2.stderr[-300:]}")
        return 1
    if "=== fn f6" in r2.stdout:
        ok("单函数模式打出了 f6 的头部")
    else:
        bad("单函数模式没有头部")

    body = [ln for ln in r2.stdout.splitlines()
            if re.match(r"^\s+\d+\s+\w", ln)]
    if len(body) == f6_ir:
        ok(f"单函数模式的 IR 条数与清单一致（{f6_ir}）")
    else:
        bad(f"条数不一致：清单 {f6_ir}，单函数 {len(body)}")

    # 3) 不存在的函数名
    r3 = subprocess.run([QLMC, "irdump", src, "no_such_fn"],
                        capture_output=True, text=True, errors="replace",
                        timeout=120)
    if r3.returncode != 0 and "找不到函数" in (r3.stderr + r3.stdout):
        ok("不存在的函数名报错退出（不静默返回空）")
    else:
        bad(f"不存在的函数名没报错 rc={r3.returncode}")

    # 4) 位置标注合法
    badloc = [ln for ln in body
              if re.search(r"dst=\d+\(", ln) and
              not re.search(r"dst=\d+\((r\d+|s\d+|\s+-|  -)\s*\)", ln)]
    if not badloc:
        ok("所有 dst 位置标注都是 r<N> / s<N> / -")
    else:
        bad(f"{len(badloc)} 条位置标注不合法，例：{badloc[0].strip()}")

    # 5) 6 参函数的栈形参必须可见
    if "PARAMSTK" in r2.stdout:
        ok("6 参函数的 PARAMSTK（栈形参）在 IR 里可见")
    else:
        bad("6 参函数的 IR 里看不到 PARAMSTK")

    try:
        os.remove(src)
    except OSError:
        pass

    print(f"\n=== IRDUMP: PASS={PASS} FAIL={FAIL} ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
