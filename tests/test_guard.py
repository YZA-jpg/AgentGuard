import io
import json
import tempfile
import unittest
from pathlib import Path

from agentguard.atbench import read_rows, run_atbench
from agentguard.guard import AgentDoG, Decision, GuardError, Review


class GuardTests(unittest.TestCase):
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
