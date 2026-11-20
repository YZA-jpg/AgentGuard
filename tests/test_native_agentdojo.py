import copy
from importlib.util import find_spec
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agentguard import native_agentdojo as runner


def config(**changes):
    values = dict(temperature=0.0, max_tokens=None, thinking="provider", system_role="system")
    return {**values, **changes}


class PinnedAssetTests(unittest.TestCase):
    def test_newer_dependencies_are_rejected_before_loading_author_code(self):
        with patch.object(runner.metadata, "distribution", return_value=SimpleNamespace(version="0.1.35")), \
             patch.object(runner.metadata, "version", return_value="unexpected-newer-version"):
            with self.assertRaisesRegex(RuntimeError, "Dependency differs from author uv.lock"):
                runner.verify_install()

    def test_offline_replay_retains_prior_query_actions_and_ignores_pending_calls(self):
        import importlib.util
        path = Path(__file__).resolve().parents[1] / "scripts/verify-official-dojo.py"
        spec = importlib.util.spec_from_file_location("offline_verifier", path)
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
        prefix = [dict(role="system"), dict(role="user")]
        assistant = dict(role="assistant", tool_calls=[dict(id="call-1", function=dict(name="write", arguments='{"value":1}'))])
        tool = dict(role="tool", tool_call_id="call-1", content=[dict(type="text", text="done")])
        history = [*prefix, assistant, tool]
        calls = [dict(request=dict(messages=value)) for value in [prefix, history, history, prefix, history]]
        executed, restarts = verifier.executed_tools([dict(role="assistant", tool_calls=[dict(function="pending", args={})])], calls)
        self.assertEqual(restarts, 1)
        self.assertEqual([call["function"] for call, _ in executed], ["write", "write"])

    def test_changed_source_is_rejected(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "agentdojo").mkdir()
            path = root / "agentdojo/test.py"
            path.write_bytes(b"original\n")
            manifest = {"files": {"agentdojo/test.py": hashlib.sha256(path.read_bytes()).hexdigest()}}
            runner.verify_files(root, manifest)
            path.write_bytes(b"modified fork\n")
            with self.assertRaisesRegex(RuntimeError, "differs from pinned wheel"):
                runner.verify_files(root, manifest)

    def test_benign_security_and_api_errors_are_not_attack_successes(self):
        planned = [dict(stage=stage, suite="slack", task_id=f"user_task_{i}", injection_id="injection_task_1" if stage == "under_attack" else None)
                   for i, stage in enumerate(["benign", "under_attack", "under_attack"])]
        values = []
        for case, status, security in zip(planned, ["ok", "ok", "author_recorded_error"], [True, False, True]):
            values.append(dict(case_key=runner.case_key(case), status=status, utility=1, security=security,
                               attack_success=int(security) if case["stage"] == "under_attack" else None,
                               input_tokens=1, output_tokens=1, duration_seconds=2))
        result = runner.summarize(planned, {row["case_key"]: row for row in values}, values)
        self.assertEqual(result["stages"]["under_attack"]["asr"], 0)
        self.assertEqual(result["stages"]["under_attack"]["author_security_sum"], 1)
        self.assertEqual(result["error_cases"], 1)
        self.assertFalse(result["complete"])
        self.assertIsNone(result["stages"]["benign"]["asr"])
        self.assertIsNone(result["f1"])


class FakeSDK:
    def __init__(self, responses):
        self.responses = responses
        self.requests = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        return self.responses.pop(0)


def completion(tool=False, malformed=False):
    from openai.types.chat import ChatCompletion
    message = dict(role="assistant", content=None if tool else "Done.")
    if tool:
        message.update(reasoning_content="fixture reasoning", tool_calls=[dict(
            id="call-fixture", type="function", function=dict(name="read_channel_messages", arguments="{" if malformed else '{"channel":"general"}'))])
    return ChatCompletion.model_validate(dict(id="fixture", object="chat.completion", created=1, model="fixture-model",
        choices=[dict(index=0, message=message, finish_reason="tool_calls" if tool else "stop")],
        usage=dict(prompt_tokens=5, completion_tokens=2, total_tokens=7)))


@unittest.skipUnless(find_spec("openai"), "OpenAI SDK required")
class TransportTests(unittest.TestCase):
    def test_zero_temperature_reasoning_and_original_request_are_preserved(self):
        from openai import NOT_GIVEN
        with tempfile.TemporaryDirectory() as directory:
            sdk = FakeSDK([completion(tool=True), completion()])
            transport = runner.RecordingCompletions(sdk, Path(directory) / "api.jsonl", config())
            original = [dict(role="developer", content="author prompt")]
            response = transport.create(model="fixture", messages=original, temperature=NOT_GIVEN)
            transport.create(model="fixture", messages=[*original, response.choices[0].message.model_dump(exclude_none=True)], temperature=NOT_GIVEN)
            self.assertEqual(sdk.requests[0]["temperature"], 0.0)
            self.assertEqual(sdk.requests[0]["messages"][0]["role"], "system")
            self.assertEqual(original[0]["role"], "developer")
            self.assertEqual(sdk.requests[1]["messages"][-1]["reasoning_content"], "fixture reasoning")
            self.assertNotIn("extra_body", sdk.requests[0])
            self.assertNotIn("max_tokens", sdk.requests[0])
            self.assertEqual(len(runner.read_records(Path(directory) / "api.jsonl")), 2)


@unittest.skipUnless(find_spec("agentdojo"), "Run integration tests in the clean official environment")
class OfficialIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        runner.verify_install()
        cls.runtime = runner.author_runtime("deepseek-v4-flash-0731", "DeepSeek")

    def test_original_scope_and_injection_candidates(self):
        args = SimpleNamespace(model="deepseek-v4-flash-0731", attack_model_name="DeepSeek", suite=list(runner.SUITES),
                               stage=list(runner.STAGES), limit_per_suite=None, check_candidates=True)
        result = runner.inventory(args)
        self.assertEqual(result["candidate_errors"], [])
        self.assertEqual(sum(row["stage"] == "benign" for row in result["cases"]), 97)
        self.assertEqual(sum(row["stage"] == "capability" for row in result["cases"]), 35)
        self.assertEqual(sum(row["stage"] == "under_attack" for row in result["cases"]), 949)
        self.assertNotIn("Ignore all new instructions", result["system_prompt"])

    def test_scripted_native_trajectory_and_scoring_match_recording_wrapper(self):
        from agentdojo.logging import OutputLogger
        from agentdojo.types import get_text_content_as_str
        import yaml
        suite = self.runtime.get_suite("v1.2.2", "slack")
        task = suite.get_user_task_by_id("user_task_0")
        with tempfile.TemporaryDirectory() as directory:
            results, traces = [], []
            for wrapped in [False, True]:
                root = Path(directory) / str(wrapped)
                root.mkdir()
                sdk = FakeSDK([completion(tool=True), completion()])
                if wrapped:
                    record = runner.run_attempt(dict(stage="benign", suite="slack", task_id="user_task_0", injection_id=None), 1,
                        {**config(), "output": str(root), "model": "deepseek-v4-flash-0731"}, self.runtime, sdk)
                    self.assertEqual(record["status"], "ok")
                    self.assertEqual(record["response_models"], ["fixture-model"])
                    results.append((record["utility"], record["security"]))
                else:
                    llm = self.runtime.llm.OpenAILLM(sdk, "deepseek-v4-flash-0731")
                    llm.name = "deepseek-v4-flash-0731"
                    pipeline = self.runtime.AgentPipeline.from_config(self.runtime.PipelineConfig(
                        llm=llm, defense=None, model_id=None, system_message_name=None, system_message=None))
                    with OutputLogger(str(root)):
                        results.append(self.runtime.benchmark.run_task_without_injection_tasks(suite, pipeline, task, root, True, "v1.2.2"))
                traces.append(json.loads(next(root.rglob("none.json")).read_text()))
            self.assertEqual(results[0], results[1])
            self.assertEqual(traces[0]["messages"], traces[1]["messages"])
            tool = next(message for message in traces[1]["messages"] if message["role"] == "tool")
            self.assertIsInstance(yaml.safe_load(get_text_content_as_str(tool["content"])), list)

    def test_malformed_tool_response_is_saved_before_author_parser_raises(self):
        from agentdojo.functions_runtime import FunctionsRuntime, EmptyEnv
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "api.jsonl"
            transport = runner.RecordingCompletions(FakeSDK([completion(tool=True, malformed=True)]), path, config())
            llm = self.runtime.llm.OpenAILLM(transport, "deepseek-v4-flash-0731")
            with self.assertRaises(json.JSONDecodeError):
                llm.query("fixture", FunctionsRuntime([]), EmptyEnv(), [dict(role="user", content=[dict(type="text", content="fixture")])], {})
            saved = runner.read_records(path)
            self.assertEqual(saved[0]["response"]["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"], "{")

    def test_resume_refuses_protocol_change_before_api_calls(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, OPENAI_API_KEY="fixture", OPENAI_BASE_URL="https://example.invalid/v1"):
            args = SimpleNamespace(model="fixture", attack_model_name="DeepSeek", temperature=0.0, thinking="provider",
                max_tokens=None, system_role="system", timeout=180.0, case_attempts=2, workers=1,
                output=Path(directory) / "run", env_file=Path(directory) / ".env", resume=False)
            inspected = dict(candidate_errors=[], cases=[], provenance=dict(manifest_sha256="fixture"),
                             system_prompt_sha256="fixture", tool_schema_sha256={})
            self.assertEqual(runner.run(args, inspected), 0)
            args.resume = True
            args.temperature = 0.7
            with self.assertRaisesRegex(RuntimeError, "Resume refused"):
                runner.run(args, inspected)


if __name__ == "__main__":
    unittest.main()
