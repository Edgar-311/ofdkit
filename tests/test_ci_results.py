"""CI must distinguish executed checks from skips and preserve failing exit status."""

import importlib.util
import io
import unittest
from pathlib import Path

_script = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "run_tests.py"
_spec = importlib.util.spec_from_file_location("ofdkit_ci_runner", _script)
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


def execute(*cases):
    result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=runner.Result).run(unittest.TestSuite(cases))
    return result


class CIResultsTest(unittest.TestCase):
    def test_skipped_required_check_fails_even_if_the_suite_is_green(self):
        case = unittest.FunctionTestCase(lambda: self.skipTest("platform unavailable"), description="required")
        result = execute(case)
        self.assertTrue(result.wasSuccessful())
        data = runner.report(result, (case.id(),))
        self.assertFalse(data["successful"])
        self.assertEqual(data["required_not_passed"], [case.id()])
        self.assertEqual(data["skipped"][0]["reason"], "platform unavailable")

    def test_executed_required_check_passes(self):
        case = unittest.FunctionTestCase(lambda: None)
        data = runner.report(execute(case), (case.id(),))
        self.assertTrue(data["successful"])
        self.assertEqual(data["passed"], [case.id()])

    def test_failure_and_error_are_preserved(self):
        def fail():
            raise AssertionError("test failure")

        def error():
            raise RuntimeError("test error")

        data = runner.report(execute(unittest.FunctionTestCase(fail), unittest.FunctionTestCase(error)))
        self.assertFalse(data["successful"])
        self.assertEqual((len(data["failures"]), len(data["errors"])), (1, 1))
        self.assertIn("test failure", data["failures"][0]["details"])

    def test_a_failed_subtest_is_not_counted_as_a_pass(self):
        class WithSubtests(unittest.TestCase):
            def runTest(self):
                with self.subTest(item=1):
                    self.assertEqual(1, 2)

        data = runner.report(execute(WithSubtests()))
        self.assertFalse(data["successful"])
        self.assertEqual(data["passed"], [])
        self.assertEqual(len(data["failures"]), 1)


if __name__ == "__main__":
    unittest.main()
