import json
import unittest

from agentguard.safetydrift_data import SafetyCase, adapt_case, development_split, reviews


class SafetyDriftDataTests(unittest.TestCase):
    def test_cli_handles_the_loader_cases_and_manifest_contract(self):
        from pathlib import Path
        from io import StringIO
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from agentguard.guard import Decision, Verdict
        from agentguard.safetydrift_data import SafetyCase
        from agentguard.safetydrift_eval import main

        class Guard:
            def reset(self):
                pass

            def review(self, context):
                return Verdict(Decision.BLOCK)

        case = SafetyCase("test", "x", 1, 0, "task", (), (
            {"candidate": {"response": "candidate"}, "thought": "", "observation": "future"},))
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, prompt, output = root / "split.json", root / "prompt.txt", root / "out.jsonl"
            manifest.write_text("{}")
            prompt.write_text("{formatted_trajectory} {tool_list_text}")
            argv = ["safetydrift_eval", "--data-root", str(root), "--split-manifest", str(manifest),
                    "--author-prompt", str(prompt), "--method", "agentdog", "--output", str(output)]
            with patch("sys.argv", argv), patch("agentguard.safetydrift_eval.selected_cases", return_value=([case], {})), \
                    patch("agentguard.safetydrift_eval.make_guard", return_value=Guard()), \
                    patch("sys.stdout", StringIO()):
                self.assertEqual(main(), 0)
            rows = [json.loads(line) for line in output.read_text().splitlines()]
            self.assertEqual(rows[-1]["tp"], 1)
            self.assertEqual(rows[-1]["total_cases"], 1)

    def test_current_results_future_observations_and_gold_are_excluded(self):
        scenario = {"task_prompt": "summarize", "expected_safe_path": "GOLD_PATH",
                    "tools": [{"name": "read", "description": "Read", "parameters": {},
                               "risk_profile": "GOLD_TOOL_RISK"}]}
        trace = {"metadata": {"scenario_category": "test", "reached_violation": True},
                 "steps": [{"action": {"raw_text": "inspect", "tool_call": {
                     "tool_name": "read", "arguments": {"file": "a"}, "result": "FUTURE_RESULT"}},
                            "observation": {"content": "FUTURE_OBSERVATION"},
                            "safety_state_after": {"risk_level": 4}},
                           {"action": {"raw_text": "finish", "tool_call": None},
                            "observation": {"content": "LATER_OBSERVATION"},
                            "safety_state_after": {"risk_level": 4}}]}
        case = adapt_case("x", trace, scenario)
        first, second = list(reviews(case))
        text = json.dumps(first.__dict__)
        for forbidden in ("FUTURE_RESULT", "FUTURE_OBSERVATION", "LATER_OBSERVATION",
                          "GOLD_TOOL_RISK", "GOLD_PATH", "risk_level", "reached_violation"):
            self.assertNotIn(forbidden, text)
        self.assertIn("FUTURE_OBSERVATION", json.dumps(second.__dict__))
        self.assertNotIn("LATER_OBSERVATION", json.dumps(second.__dict__))
        self.assertEqual(case.first_hazard, 0)

    def test_duplicate_test_content_is_removed_from_development_pool(self):
        def case(case_id, task):
            return SafetyCase(case_id, "category", 0, None, task, (), ())
        rows = [case("test", "same"), case("leak", "same"), case("a", "unique-a"),
                case("a-duplicate", "unique-a"), case("b", "unique-b"), case("c", "unique-c")]
        train, calibration, discarded = development_split(rows, ["test"])
        self.assertEqual(set(discarded), {"leak", "a-duplicate"})
        self.assertEqual(set(train) | set(calibration), {"a", "b", "c"})
        self.assertFalse(set(train) & set(calibration))

    def test_first_intervention_timing_excludes_post_action_evidence(self):
        from agentguard.guard import Decision, Verdict
        from agentguard.safetydrift_data import SafetyCase
        from agentguard.safetydrift_eval import evaluate_case, summarize

        class Guard:
            def reset(self):
                self.calls = 0

            def review(self, context):
                self.calls += 1
                self.last_input = context
                return Verdict(Decision.BLOCK)

        guard = Guard()
        steps = tuple({"candidate": {"name": "act", "arguments": {}}, "thought": "",
                       "observation": f"future-{i}"} for i in range(3))
        case = SafetyCase("unsafe", "x", 1, 2, "task", (), steps)
        record = evaluate_case(case, guard)
        self.assertEqual(guard.calls, 1)
        self.assertNotIn("future-0", json.dumps(guard.last_input.__dict__))
        summary = summarize([record])
        self.assertEqual(summary["phir"], 1.0)
        self.assertEqual(summary["mas"], 2)
        self.assertEqual(summary["recall"], 1.0)

    def test_author_prompt_includes_candidate_and_no_future_result(self):
        from agentguard.guard import Review
        from agentguard.safetydrift_eval import proposed_action_prompt

        review = Review(({"role": "user", "content": "task"},), "task",
                        {"name": "candidate-tool", "arguments": {"x": 1}}, ())
        prompt = proposed_action_prompt("{formatted_trajectory}\n{tool_list_text}", review)
        self.assertIn("candidate-tool", prompt)
        self.assertIn("has not executed", prompt)
