import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / "scripts/run-model-diagnostic.py"
spec = importlib.util.spec_from_file_location("model_diagnostic", path)
diagnostic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostic)


class DiagnosticDesignTests(unittest.TestCase):
    def test_sampling_is_balanced_reproducible_and_input_order_independent(self):
        records = [dict(stage="under_attack", suite=suite, task_id=f"user_task_{uid}", injection_id=f"injection_task_{iid}")
                   for suite in diagnostic.native.SUITES for uid in range(6) for iid in range(5)]
        first = diagnostic.select_cases(records)
        second = diagnostic.select_cases(list(reversed(records)))
        self.assertEqual(first, second)
        self.assertEqual(len(first), 40)
        self.assertEqual(len({diagnostic.native.case_key(case) for case in first}), 40)
        for suite in diagnostic.native.SUITES:
            self.assertEqual(sum(case["suite"] == suite for case in first), 10)
        self.assertNotEqual(first, diagnostic.select_cases(records, seed=43))

    def test_request_settings_only_vary_model_or_temperature(self):
        conditions = diagnostic.CONDITIONS
        args = [diagnostic.condition_args(group, Path("unused"), 4) for group in conditions]
        values = [vars(arg).copy() for arg in args]
        self.assertEqual(args[0].temperature, 0.0)
        self.assertEqual(args[1].temperature, 0.0)
        self.assertIsNone(args[2].temperature)
        self.assertNotEqual(args[0].model, args[1].model)
        self.assertEqual(args[1].model, args[2].model)
        for value in values:
            value.pop("model")
            value.pop("temperature")
        self.assertEqual(values[0], values[1])
        self.assertEqual(values[1], values[2])
        self.assertEqual(args[0].thinking, "enabled")
        self.assertEqual(args[0].attack_model_name, "DeepSeek")


if __name__ == "__main__":
    unittest.main()
