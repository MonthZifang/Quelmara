"""Benchmark driver regression tests; only Python children/mocks, no toolchains."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "speed_run_under_test", Path(__file__).resolve().parents[1] / "bench/speed/run.py")
run = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(run)


class ProcessTests(unittest.TestCase):
    def test_legacy_success_tuple_and_memory_path(self):
        for memory in (False, True):
            with self.subTest(memory=memory):
                seconds, peak, output = run.run_once(
                    sys.executable, ["-c", "print('ok')"], sample_mem=memory)
                self.assertGreater(seconds, 0)
                self.assertGreaterEqual(peak, 0)
                self.assertEqual(output, "ok\n")

    def test_nonzero_even_with_valid_protocol(self):
        with self.assertRaisesRegex(run.BenchmarkError, "exit code 7.*stderr='oops"):
            run.run_once(sys.executable, ["-c", "import sys; print('x\\nT\\n1'); "
                          "sys.stderr.write('oops'); sys.exit(7)"])

    def test_timeout_kills_and_reaps(self):
        child = mock.Mock()
        child.communicate.side_effect = [subprocess.TimeoutExpired(["fake"], 0.01),
                                         ("partial", "diagnostic")]
        with mock.patch.object(run.subprocess, "Popen", return_value=child):
            with self.assertRaisesRegex(run.BenchmarkError, "timeout.*diagnostic"):
                run.run_once("fake", timeout=0.01)
        child.kill.assert_called_once_with()
        self.assertEqual(child.communicate.call_count, 2)

    def test_large_pipes_do_not_deadlock_memory_mode(self):
        _, _, output = run.run_once(sys.executable, ["-c",
            "import sys; sys.stdout.write('x'*100000); sys.stderr.write('e'*100000)"],
            sample_mem=True, timeout=5)
        self.assertEqual(len(output), 100000)


class ProtocolTests(unittest.TestCase):
    def test_valid_multiline_preserves_checksum_whitespace(self):
        self.assertEqual(run.parse_out(" a \r\nb\r\nT\r\n12\r\n"), (" a \nb", 12))

    def test_invalid_protocol_never_falls_back(self):
        for output in ("", "42", "T\n1", "x\nT", "x\nT\n0", "x\nT\n-1",
                       "x\nT\n1.0", "x\nT\n1\nextra", "x\nT\n1\nT\n2",
                       "x\n\nT\n1", "x\nT\n 1"):
            with self.subTest(output=output), self.assertRaises(run.BenchmarkError):
                run.parse_out(output)

    def test_nonfastest_round_checksum_is_checked(self):
        with mock.patch.object(run, "run_once", side_effect=[
                (1, 0, "a\nT\n1\n"), (1, 0, "b\nT\n100\n")]):
            cell = run.measure(["fake"], 2)
        self.assertEqual(cell["status"], "failed")
        self.assertNotIn("best_ns", cell)
        self.assertEqual([r["ns"] for r in cell["rounds"]], [1, 100])

    def test_every_round_and_minimum_retained(self):
        with mock.patch.object(run, "run_once", side_effect=[
                (1, 3, "a\nT\n9\n"), (2, 4, "a\nT\n2\n")]):
            cell = run.measure(["fake"], 2)
        self.assertEqual(cell["best_ns"], 2)
        self.assertEqual(cell["peak_bytes"], 4)
        self.assertEqual([r["ns"] for r in cell["rounds"]], [9, 2])

    def test_bad_round_cannot_be_hidden_by_good_round(self):
        for error in (run.BenchmarkError("exit code 1"), OSError("missing")):
            with mock.patch.object(run, "run_once", side_effect=[error,
                    (1, 0, "a\nT\n2\n")]):
                cell = run.measure(["fake"], 2)
            self.assertEqual(cell["status"], "failed")
            self.assertEqual(len(cell["rounds"]), 2)
            self.assertNotIn("best_ns", cell)


class MainTests(unittest.TestCase):
    def invoke(self, languages, built, notes=None, outputs=None, markdown=False):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            argv = ["run.py", "--langs", *languages, "--reps", "2", "--json", str(path)]
            if markdown:
                argv.append("--markdown")
            stream = io.StringIO()
            with mock.patch.object(sys, "argv", argv), \
                 mock.patch.object(run, "BENCHES", [("b1_int", "test")]), \
                 mock.patch.object(run, "build_all", return_value=(built, notes or {})), \
                 mock.patch.object(run, "run_once", side_effect=outputs), \
                 mock.patch.object(run, "compiler_metadata", return_value={"invocations": []}), \
                 mock.patch.object(run, "heap_mb_from_toml", return_value=None), \
                 mock.patch.object(run, "bounds_check_from_toml", return_value=None), \
                 contextlib.redirect_stdout(stream):
                code = run.main()
            return code, json.loads(path.read_text()), stream.getvalue()

    def test_output_directory_isolated_and_default_json_follows(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "isolated"
            with mock.patch.object(sys, "argv", ["run.py", "--langs", "python",
                    "--only", "b1_int", "--output-dir", str(folder)]), \
                 mock.patch.object(run, "OUT", run.OUT), \
                 mock.patch.object(run, "build_all", return_value=({}, {})), \
                 mock.patch.object(run, "compiler_metadata", return_value={}), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run.main(), 1)
                self.assertEqual(run.OUT, str(folder.resolve()))
            payload = json.loads((folder / "results.json").read_text())
            self.assertEqual(payload["options"]["output_dir"], str(folder.resolve()))

    def test_single_language_not_cross_language_pass(self):
        code, payload, output = self.invoke(["python"], {("python", "b1_int"): ["fake"]},
            outputs=[(1, 0, "a\nT\n4\n"), (1, 0, "a\nT\n2\n")])
        self.assertEqual(code, 0)
        row = payload["benchmarks"][0]
        self.assertEqual(row["validation"], "single_language_unverified")
        self.assertIn("SINGLE_LANGUAGE_UNVERIFIED", output)
        self.assertEqual(row["results"]["python"]["rounds"][1]["ns"], 2)
        self.assertIn("platform", payload)
        self.assertIn("compilers", payload)
        self.assertIn("build_options", payload)

    def test_complete_cross_language_pass(self):
        code, payload, _ = self.invoke(["c", "python"],
            {("c", "b1_int"): ["fake"], ("python", "b1_int"): ["fake"]},
            outputs=[(1, 0, "a\nT\n2\n")] * 4)
        self.assertEqual(code, 0)
        self.assertEqual(payload["benchmarks"][0]["validation"], "cross_language_pass")

    def test_mismatch_fails_both_output_modes_and_removes_table_timings(self):
        for markdown in (False, True):
            code, payload, output = self.invoke(["c", "python"],
                {("c", "b1_int"): ["fake"], ("python", "b1_int"): ["fake"]},
                outputs=[(1, 0, "a\nT\n2\n")] * 2 + [(1, 0, "b\nT\n3\n")] * 2,
                markdown=markdown)
            self.assertEqual(code, 1)
            self.assertEqual(payload["benchmarks"][0]["t"], {})
            self.assertIn("MISMATCH", output)

    def test_missing_all_retained_and_saved(self):
        code, payload, output = self.invoke(["c"], {}, {"c": "missing compiler"})
        self.assertEqual(code, 1)
        self.assertEqual(payload["benchmarks"][0]["results"]["c"]["status"], "missing")
        self.assertIn("missing compiler", output)

    def test_partial_missing_is_explicit_not_cross_language_pass(self):
        code, payload, output = self.invoke(["c", "python"],
            {("python", "b1_int"): ["fake"]}, {"c": "missing compiler"},
            outputs=[(1, 0, "a\nT\n2\n")] * 2)
        self.assertEqual(code, 0)  # optional toolchains remain skippable
        self.assertEqual(payload["benchmarks"][0]["validation"], "incomplete")
        self.assertIn("MISSING", output)

    def test_compile_failure_is_not_an_optional_missing_toolchain(self):
        code, payload, _ = self.invoke(["c"], {}, {"c": "b1_int 编译失败: bad"})
        self.assertEqual(code, 1)
        self.assertEqual(payload["benchmarks"][0]["results"]["c"]["status"], "failed")

    def test_qlmc_path_and_wine_runner_are_separate_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            compiler = Path(directory) / "compiler with spaces.exe"
            compiler.touch()
            with mock.patch.dict(run.os.environ, {"QLMC": str(compiler), "WINE": "/fake/wine"}), \
                 mock.patch.object(run, "IS_WIN", False), \
                 mock.patch.object(run, "OUT", directory), \
                 mock.patch.object(run, "BENCHES", [("b1_int", "test")]), \
                 mock.patch.object(run.os, "chmod"), \
                 mock.patch.object(run, "_build_run", return_value=
                                   subprocess.CompletedProcess([], 0, "", "")) as build:
                built, notes = run.build_all(["quelmara"], None)
            self.assertEqual(build.call_args.args[0][:2], ["/fake/wine", str(compiler)])
            self.assertIn(("quelmara", "b1_int"), built)
            self.assertEqual(notes, {})

    def test_build_launch_and_timeout_errors_are_reportable(self):
        for error in (OSError("missing compiler"), subprocess.TimeoutExpired(["fake"], 1)):
            with mock.patch.object(run.subprocess, "run", side_effect=error):
                result = run._build_run(["fake"], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(result.stderr)

    def test_build_rc_zero_requires_new_nonempty_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "output"
            for initial in (None, b"old"):
                if initial is not None:
                    artifact.write_bytes(initial)
                with mock.patch.object(run.subprocess, "run", return_value=
                        subprocess.CompletedProcess([], 0, "", "")):
                    result = run._build_run(["fake"], expected_output=str(artifact))
                self.assertEqual(result.returncode, 1)
                self.assertIn("no fresh nonempty artifact", result.stderr)
                if initial is not None:
                    self.assertEqual(artifact.read_bytes(), initial)  # never delete stale outputs
            def compile_output(*args, **kwargs):
                artifact.write_bytes(b"new artifact, different size")
                return subprocess.CompletedProcess([], 0, "", "")
            with mock.patch.object(run.subprocess, "run", side_effect=compile_output):
                result = run._build_run(["fake"], expected_output=str(artifact))
            self.assertEqual(result.returncode, 0)

    def test_build_notes_preserve_every_failure(self):
        notes = {}
        run._note(notes, "c", "b1 failed")
        run._note(notes, "c", "b2 failed")
        self.assertEqual(notes["c"], "b1 failed\nb2 failed")

    def test_invalid_repetitions_and_timeouts(self):
        for flags in (["--reps", "0"], ["--reps", "-1"], ["--timeout", "0"],
                      ["--timeout", "nan"], ["--timeout", "inf"]):
            with mock.patch.object(sys, "argv", ["run.py", *flags]), \
                 contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
                run.main()
            self.assertEqual(exc.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
