import io
import json
import tempfile
import unittest
from pathlib import Path

from agentguard.atbench import author_trajectory_prompt, read_rows, run_atbench
from agentguard.guard import AgentDoG, Decision, GuardError, Review


class GuardTests(unittest.TestCase):
    def test_author_format_includes_tool_schema_without_gold_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder) / "test.json"
            data.write_text(json.dumps([{
                "id": 1, "label": 1, "reason": "gold-only",
                "tool_used": [{"name": "lookup", "description": "Read a record",
                               "parameters": {"type": "object"}, "_source": "provenance-only"}],
                "contents": [[{"role": "user", "content": "Look up a record."},
                              {"role": "agent", "thought": "Read first", "action": "lookup"},
                              {"role": "environment", "content": "Returned a record"}]],
            }]), encoding="utf-8")
            _, cases = read_rows(data, "ATBench", (), None, include_tools=True)
            prompt = author_trajectory_prompt("{formatted_trajectory}\n{tool_list_text}", cases[0][2])
            for text in ("[USER]", "[AGENT]", "[THOUGHT]", "[ACTION]", "[ENVIRONMENT]", "Read a record"):
                self.assertIn(text, prompt)
            self.assertNotIn("gold-only", prompt)
            self.assertNotIn("provenance-only", prompt)
            self.assertNotIn("_source", prompt)

    def test_requires_one_designated_judgment(self):
        context = Review(())
        self.assertEqual(
            AgentDoG(lambda _: "<Analysis>Consider unsafe inputs.</Analysis><Judgment>safe</Judgment>")
            .review(context).decision,
            Decision.ALLOW,
        )
        for text in ("unsafe", "<Judgment>safe</Judgment><Judgment>unsafe</Judgment>"):
            with self.subTest(text=text), self.assertRaises(GuardError):
                AgentDoG(lambda _: text).review(context)

    def test_official_schemas_keep_gold_out_of_the_prompt(self):
        for config, id_key, history_key in (
            ("ATBench", "id", "contents"),
            ("ATBench500", "conv_id", "content"),
        ):
            with self.subTest(config=config), tempfile.TemporaryDirectory() as folder:
                data = Path(folder) / "test.json"
                data.write_text(json.dumps([
                    {id_key: "pass", history_key: [[{"role": "user", "content": "normal task"}]], "label": 0},
                    {id_key: "fail", history_key: [[{"role": "user", "content": "other task"}]], "label": 1,
                     "reason": "gold-only-reason", "risk_source": "gold-only-source"},
                    {id_key: "error", history_key: [[{"role": "user", "content": "error task"}]], "label": 1},
                ]), encoding="utf-8")
                _, cases = read_rows(data, config, (), None)

                def generate(prompt):
                    self.assertNotIn("gold-only", prompt)
                    if "normal task" in prompt:
                        return "<Judgment>safe</Judgment>"
                    if "other task" in prompt:
                        return "<Judgment>unsafe</Judgment>"
                    return ""

                output = io.StringIO()
                summary = run_atbench(AgentDoG(generate), cases, output)
                self.assertEqual((summary["tp"], summary["tn"], summary["error_cases"]), (1, 1, 1))
                self.assertEqual(len(output.getvalue().splitlines()), 4)


if __name__ == "__main__":
    unittest.main()
