import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from agentguard.guard import Decision, GuardError, Verdict


@unittest.skipUnless(os.getenv("IPIGUARD_ROOT"), "Set IPIGUARD_ROOT to test the live adapter")
class ExecutorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(os.environ["IPIGUARD_ROOT"]).resolve()
        sys.path[:0] = [str(root), str(root / "agentdojo" / "src")]
        from agentdojo.functions_runtime import EmptyEnv, FunctionCall
        from agentguard.agentdojo import GuardedToolsExecutor

        cls.call_type = FunctionCall
        cls.env = EmptyEnv()
        cls.executor_type = GuardedToolsExecutor

    def setUp(self):
        self.executed = []
        params = SimpleNamespace(model_json_schema=lambda: {"type": "object"})
        tools = {name: SimpleNamespace(name=name, description=name, parameters=params)
                 for name in ("write", "read")}

        def execute(env, name, args):
            self.executed.append((name, args))
            return "observed read result", None

        self.runtime = SimpleNamespace(functions=tools, run_function=execute)

    def test_blocked_call_has_no_side_effect_and_no_future_tool_result(self):
        contexts = []
        decisions = iter([Decision.ALLOW, Decision.BLOCK])
        guard = SimpleNamespace(review=lambda review: contexts.append(review) or Verdict(next(decisions)),
                                reset=lambda: None)
        executor = self.executor_type(guard)
        calls = [
            self.call_type(function="read", args={"items": "['item']"}, id="1"),
            self.call_type(function="write", args={"destination": "external"}, id="2"),
        ]
        messages = [{"role": "user", "content": []},
                    {"role": "assistant", "content": None, "tool_calls": calls}]
        _, _, _, result, _ = executor.query("read only", self.runtime, self.env, messages, {})
        self.assertEqual(self.executed, [("read", {"items": ["item"]})])
        self.assertEqual([msg["tool_call_id"] for msg in result[-2:]], ["1", "2"])
        self.assertIn("not executed", result[-1]["error"])
        self.assertEqual(contexts[0].candidate["args"], {"items": ["item"]})
        self.assertNotIn("external", repr(contexts[0].history))
        self.assertIn("observed read result", repr(contexts[1].history))
        self.assertEqual([e["decision"] for e in executor.events], [Decision.ALLOW, Decision.BLOCK])
        executor.reset()
        self.assertEqual(executor.events, [])

    def test_guard_error_leaves_tool_unexecuted(self):
        def review(context):
            raise GuardError("test failure")

        guard = SimpleNamespace(review=review)
        executor = self.executor_type(guard)
        call = self.call_type(function="write", args={}, id="1")
        messages = [{"role": "assistant", "content": None, "tool_calls": [call]}]
        with self.assertRaises(GuardError):
            executor.query("test", self.runtime, self.env, messages, {})
        self.assertEqual(self.executed, [])
        self.assertEqual(executor.events[0]["decision"], Decision.ERROR)


if __name__ == "__main__":
    unittest.main()
