import unittest

from agentguard.guard import GuardError, Review
from agentguard.shieldagent_eval import configure_context, encode_bounded_prompt, format_atbench, parse_answer


class ShieldAgentTests(unittest.TestCase):
    def test_truncation_preserves_the_assistant_boundary_and_budget(self):
        class Tokenizer:
            def __call__(self, text, **kwargs):
                return {"input_ids": list(text)}
        suffix = "<|im_end|>\n<|im_start|>assistant\n"
        prompt = "<|im_start|>user\n" + "x" * 200 + suffix
        ids, full_length = encode_bounded_prompt(Tokenizer(), prompt, 80)
        self.assertEqual(len(ids), 80)
        self.assertEqual(full_length, len(prompt))
        self.assertTrue("".join(ids).endswith(suffix))
        self.assertTrue("".join(ids).startswith("<|im_start|>user\n"))
    def test_yarn_preserves_checkpoint_frequency_and_native_config_is_unchanged(self):
        from types import SimpleNamespace
        config = SimpleNamespace(rope_parameters={"rope_type": "default", "rope_theta": 1000000},
                                 max_position_embeddings=32768)
        self.assertEqual(configure_context(config, "native32k").max_position_embeddings, 32768)
        configure_context(config, "yarn128k")
        self.assertEqual(config.rope_parameters["rope_theta"], 1000000)
        self.assertEqual(config.rope_parameters["original_max_position_embeddings"], 32768)
        self.assertEqual(config.max_position_embeddings, 131072)
    def test_maps_calls_and_observations_without_gold_annotations(self):
        context = Review(({"role": "user", "content": "task"},
                          {"role": "agent", "thought": "inspect", "gold_reason": "HIDDEN_GOLD",
                           "action": '{"name":"read","arguments":{"path":"x"}}'},
                          {"role": "environment", "content": "result"}),
                         tools=({"name": "read", "description": "Read a file", "parameters": {}},))
        dialog, env = format_atbench(context)
        self.assertIn("<Assistant calls the tool>", dialog)
        self.assertIn("atbench_call_1", dialog)
        self.assertIn("<Tool>", dialog)
        self.assertIn("Read a file", env)
        self.assertNotIn("label", dialog)
        self.assertNotIn("HIDDEN_GOLD", dialog)

    def test_short_answer_is_accepted_without_guessing_missing_output(self):
        original_parser = lambda text: text.split("[Answer] ")[-1].split("\n")[0] if "\n" in text else ""
        self.assertEqual(parse_answer("[Answer] unsafe\n[Analysis] evidence", original_parser), 1)
        self.assertEqual(parse_answer("[Answer] safe", original_parser), 0)
        with self.assertRaises(GuardError):
            parse_answer("Probably fine", original_parser)
        with self.assertRaises(GuardError):
            parse_answer("[Answer] safe\n[Answer] unsafe\n", original_parser)
