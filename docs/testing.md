# Test records

From a source checkout with ofdkit installed, run the same recorder used in CI:

```bash
python .github/scripts/run_tests.py --require-windows-junctions
```

It keeps `test-output.txt` (the readable log) and `test-results.json` (successful tests,
failures, errors and skip reasons). On GitHub Actions it also writes the counts and
the status of both Windows directory junction checks to the job summary. CI uploads
both files as a `test-results-...` artifact for 14 days, including failed test runs.
An installation or checkout failure may happen before any test record is created.

The Windows core job requires the guard's directory junction check to pass. With MCP
installed, the server's junction check must pass too. A missing or skipped required
check fails the job, even when unittest otherwise reports OK. On Linux and macOS,
the Windows-only tests may skip normally. Other skip reasons remain visible in JSON.

Set `OFD_SAMPLES_DIR` to a checkout of `Edgar-311/ofd-samples` to include the shared
sample checks. MCP and MarkItDown tests require the respective optional dependencies;
openpyxl is only used to read back the Excel files in tests.

The standard command remains available:

```bash
python -m unittest discover -s tests -t . -v
```

Counts of failure/error events can exceed the number of test methods when a method
has several failing subtests. A method with a failing subtest is not counted as passed.
