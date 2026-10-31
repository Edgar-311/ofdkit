"""Run unittest and retain readable logs, structured results, and a GitHub summary."""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path

JUNCTION_TESTS = (
    "tests.test_guard.GuardTest.test_directory_junction_to_outside_is_not_entered",
    "tests.test_mcp.InProcessTest.test_root_holds_against_directory_junctions",
)


class Result(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.passed: list[str] = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.passed.append(test.id())


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, value):
        for stream in self.streams:
            stream.write(value)
        return len(value)

    def flush(self):
        for stream in self.streams:
            stream.flush()


def report(result: Result, required: tuple[str, ...] = ()) -> dict:
    missing = [name for name in required if name not in result.passed]
    return {
        "tests_run": result.testsRun,
        "passed": result.passed,
        "failures": [{"test": test.id(), "details": detail} for test, detail in result.failures],
        "errors": [{"test": test.id(), "details": detail} for test, detail in result.errors],
        "skipped": [{"test": test.id(), "reason": reason} for test, reason in result.skipped],
        "expected_failures": [{"test": test.id(), "details": detail} for test, detail in result.expectedFailures],
        "unexpected_successes": [test.id() for test in result.unexpectedSuccesses],
        "required_not_passed": missing,
        "successful": result.wasSuccessful() and not missing,
    }


def summary(data: dict) -> str:
    lines = [
        "## Test results",
        "",
        "| Run | Passed | Failure events | Error events | Skipped |",
        "| ---: | ---: | ---: | ---: | ---: |",
        f"| {data['tests_run']} | {len(data['passed'])} | {len(data['failures'])} | {len(data['errors'])} | {len(data['skipped'])} |",
        "",
        "Download the test-results artifact for the complete log and skip reasons.",
        "",
        "| Windows directory junction check | Result |",
        "| --- | --- |",
    ]
    skipped = {item["test"] for item in data["skipped"]}
    for name in JUNCTION_TESTS:
        status = "passed" if name in data["passed"] else "skipped" if name in skipped else "not passed"
        lines.append(f"| `{name}` | {status} |")
    if data["required_not_passed"]:
        lines += ["", "**A required Windows junction check did not pass; this job fails.**"]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-windows-junctions", action="store_true")
    args = parser.parse_args(argv)
    required = ()
    if args.require_windows_junctions and sys.platform == "win32":
        required = JUNCTION_TESTS if importlib.util.find_spec("mcp") is not None else JUNCTION_TESTS[:1]
    # Discovery starts at the repository root, matching the documented test command.
    suite = unittest.defaultTestLoader.discover("tests", top_level_dir=".")
    with open("test-output.txt", "w", encoding="utf-8") as log:
        with contextlib.redirect_stdout(Tee(sys.stdout, log)), contextlib.redirect_stderr(Tee(sys.stderr, log)):
            runner = unittest.TextTestRunner(stream=sys.stderr, verbosity=2, resultclass=Result)
            result = runner.run(suite)
    data = report(result, required)
    Path("test-results.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as stream:
            stream.write(summary(data))
    if data["required_not_passed"]:
        print("Required junction checks did not pass: " + ", ".join(data["required_not_passed"]), file=sys.stderr)
    return 0 if data["successful"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
