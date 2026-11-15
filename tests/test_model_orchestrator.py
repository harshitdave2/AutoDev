import io
import time
import unittest
from contextlib import redirect_stdout

from models.base_model import BaseModel
from models.model_orchestrator import ModelOrchestrator, _is_permanent_failure

VALID = '{"candidate_1": "def f():\\n    return 1"}'


class FakeModel(BaseModel):
    def __init__(self, name, delay=0.0, error=None, output=VALID):
        self.model_name = name
        self.delay = delay
        self.error = error
        self.output = output
        self.calls = 0

    def generate_fix(self, prompt, language="python"):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.error:
            raise self.error
        return self.output


class StatusError(Exception):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.status_code = status_code


def run(orchestrator):
    with redirect_stdout(io.StringIO()) as out:
        results = orchestrator.generate_parallel("fix it")
    return results, out.getvalue()


class OrchestratorTests(unittest.TestCase):
    def test_timeout_is_enforced_and_fast_result_is_kept(self):
        slow, fast = FakeModel("slow", delay=5), FakeModel("fast")
        orchestrator = ModelOrchestrator([slow, fast], timeout=1, per_model_retries=0)
        started = time.monotonic()
        results, _ = run(orchestrator)
        self.assertLess(time.monotonic() - started, 3.0)  # previously blocked ~5s
        self.assertEqual(results, [VALID])
        self.assertEqual(orchestrator.last_successful_model, "fast")

    def test_results_follow_model_priority_not_completion_order(self):
        first = FakeModel("first", delay=0.3, output='{"candidate_1": "def a():\\n    return 1"}')
        second = FakeModel("second", output='{"candidate_1": "def b():\\n    return 2"}')
        orchestrator = ModelOrchestrator([first, second], timeout=5)
        results, _ = run(orchestrator)
        self.assertIn("def a", results[0])
        self.assertIn("def b", results[1])
        self.assertEqual(orchestrator.last_successful_model, "first")

    def test_transient_error_with_429_digits_is_retried(self):
        model = FakeModel("m", error=RuntimeError("connection reset on port 54290"))
        _, _ = run(ModelOrchestrator([model], timeout=5, per_model_retries=2))
        self.assertEqual(model.calls, 3)

    def test_real_rate_limit_is_not_retried(self):
        model = FakeModel("m", error=StatusError("Too Many Requests", 429))
        _, _ = run(ModelOrchestrator([model], timeout=5, per_model_retries=2))
        self.assertEqual(model.calls, 1)

    def test_permanent_failure_classifier(self):
        self.assertTrue(_is_permanent_failure(StatusError("x", 401)))
        self.assertTrue(_is_permanent_failure(RuntimeError("You exceeded your current quota")))
        self.assertTrue(_is_permanent_failure(RuntimeError("Error code: 429 - slow down")))
        self.assertFalse(_is_permanent_failure(StatusError("boom", 500)))
        self.assertFalse(_is_permanent_failure(RuntimeError("took 54290 ms")))
        self.assertFalse(_is_permanent_failure(RuntimeError("line 4290 of file")))

    def test_rich_markup_does_not_leak_into_output(self):
        _, output = run(ModelOrchestrator([FakeModel("m")], timeout=5))
        self.assertNotIn("[dim]", output)
        self.assertIn("Routing to m", output)

    def test_error_text_with_brackets_cannot_break_logging(self):
        model = FakeModel("m", error=RuntimeError("bad [/oops] tag"))
        results, _ = run(ModelOrchestrator([model], timeout=5, per_model_retries=0))
        self.assertEqual(results, [])

    def test_all_models_failing_returns_empty_list(self):
        models = [FakeModel("a", error=RuntimeError("x")), FakeModel("b", output="")]
        results, _ = run(ModelOrchestrator(models, timeout=5, per_model_retries=0))
        self.assertEqual(results, [])

    def test_no_models_raises(self):
        with self.assertRaises(Exception):
            ModelOrchestrator([]).generate_parallel("x")


if __name__ == "__main__":
    unittest.main()

