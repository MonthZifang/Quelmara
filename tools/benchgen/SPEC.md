# Benchmark source-generation SPEC (Quelmara cross-language suite)

You are adding benchmark sources for the Quelmara language-comparison suite under
`/root/Quelmara/Quelmara/bench/speed/`.

## Goal
For your language, write `bench/speed/<lang>/<bench>.<ext>` for as many of the 76
benchmark IDs as possible, such that each prints a **byte-identical** "checksum"
to the canonical C implementation.

## Canonical spec = the C sources
`bench/speed/c/*.c` are the AUTHORITATIVE specification. Replicate the ALGORITHM
EXACTLY: same loop bounds, same 64-bit signed integer types, same operations,
same output values. Do NOT "improve" or change the algorithm. Existing examples
for your language (if any) live in `bench/speed/<lang>/` — match their style.

## Output format (CRITICAL)
Each program must:
1. Print zero or more lines that form the **checksum** (the exact same text C prints
   before its `T` line — usually decimal integers printed with `%lld`, or `%.6f`
   for the floating benches).
2. Print exactly a line `T`.
3. Print a line with the elapsed nanoseconds (integer).

The runner compares the text **before** the `T` line across all languages. If any
language differs by even one byte, the whole bench row FAILS the differential gate
and CI goes red. So byte-exactness is mandatory.

## Reference checksums
`/tmp/c_checksums.json` maps `bench_id -> expected checksum string` (all lines
before `T`, joined by `\n`). Your output for each bench MUST equal this string.

## Verify locally
`tools/benchgen/verify_lang.py` compiles+runs each of your files and compares to
C. Run:
```
python3 tools/benchgen/verify_lang.py <lang>
```
Iterate until it reports `mismatch=0` for every file you commit. Benchmarks you
genuinely cannot replicate byte-for-byte (and ONLY those) may be LEFT OUT — the
runner treats an absent file as a SKIP (not a failure). Try hard to include all 76.

## Hard points (per-bench)
- 64-bit signed integers everywhere (long long / i64 / int64 / Int64 / int). Never
  overflow; array/seed sizes are large.
- Floating benches: `b2_float`, `b16_leibniz`, `b66_integrate`. Print with exactly
  6 decimals (`%.6f` in C). Compute in double/f64. If your language's `%.6f` of the
  identical double differs from C in the last digit, you MAY skip that bench.
- String benches: `b5_string`, `b46_strcat`, `b76_io_line`. The C output is an
  INTEGER (e.g. the accumulated length or sum), NOT the literal strings. Match the
  integer C prints. Do not print the actual strings.
- Recursion benches (b3, b10, b11, b50, b58, b77, b79) must use the same recursion.
- Concurrency: `b8_threads1` / `b8_threads4` / `b53_thread_sim` — if your language
  makes this hard, replicate the *result* (the deterministic sum) without real
  threads if needed, but it must match C's checksum exactly.

## Don't touch
Do NOT modify `run.py`, `tools/benchgen/*`, or any files outside
`bench/speed/<lang>/`. Don't commit/push — the lead will commit.

## Report
After verifying, report: how many of the 76 benches matched, and list any skipped
benches with the reason.
