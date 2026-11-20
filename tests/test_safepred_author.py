import copy
import json
from pathlib import Path
import unittest

from agentguard.guard import Decision, GuardError, Review
from agentguard.safepred_author import (AUTHOR_REVISION, AuthorSafePred, author_world,
                                        extract_policies, fit_state, load_author, recorded_state)

ROOT = Path(__file__).resolve().parents[1] / 'vendor/SafePred-official'


class Transport:
    max_tokens = 4000
    input_limit = 1000000

    def __init__(self, output):
        self.output = output
        self.calls = []

    def generate(self, prompt, **kwargs):
        self.calls.append({'prompt': prompt, 'response': self.output})
        return self.output

    def count_prompt(self, prompt):
        return len(prompt)

    def encode(self, text):
        return list(text)

    def decode(self, ids):
        return ''.join(ids)


def forecast(ids):
    return json.dumps({'semantic_delta': 'The tool returns the requested data.',
                       'long_term_impact': 'Continue the task.',
                       'element_changes': {'new_elements': [], 'removed_elements': []},
                       'risk_explanation': 'Violation' if ids else '',
                       'violated_policy_ids': ids, 'optimization_guidance': 'Use a safe action' if ids else None,
                       'risk_score': 0.01})


@unittest.skipUnless((ROOT / '.git').exists(), 'Pinned author checkout not installed')
class AuthorSafePredTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.author = load_author(ROOT)
        cls.policies = [cls.author.extractor._get_goal_alignment_policy(None),
                        {'policy_id': 'P001', 'policy_description': 'Do not disclose private credentials.',
                         'scope': 'Tool calls', 'risk_level': 'high', 'definitions': []}]

    def context(self):
        return Review(({'role': 'user', 'content': 'Read the document'},
                       {'role': 'environment', 'content': 'Visible state'},
                       {'role': 'agent', 'thought': 'Inspect the file', 'gold_reason': 'HIDDEN_GOLD'}),
                      'Read the document', {'name': 'read', 'arguments': {'path': 'x'}},
                      ({'name': 'read', 'description': 'Read a file'},))

    def test_native_prompt_parser_score_and_root_decision_are_used(self):
        for ids, decision, risk in [([], Decision.ALLOW, 0.0), (['P001'], Decision.BLOCK, 0.8)]:
            with self.subTest(ids=ids):
                transport = Transport(forecast(ids))
                guard = AuthorSafePred(self.author, transport, self.policies)
                state, action, _, _ = recorded_state(self.context(), self.author)
                expected_prompt = self.author.prompt.world_model_state_delta(
                    state=state, action=action, policies=self.policies, show_policy_references=False,
                    enable_short_term_prediction=True, enable_long_term_prediction=True)
                verdict = guard.review(self.context())
                self.assertEqual((verdict.decision, verdict.risk_score), (decision, risk))
                self.assertEqual(transport.calls[0]['prompt'], expected_prompt)
                self.assertNotIn('HIDDEN_GOLD', expected_prompt)
                native = author_world(self.author, Transport(forecast(ids)))
                native.simulate(state, action, policies=self.policies)
                self.assertEqual(native._last_predicted_delta, verdict.details['forecast'])

    def test_native_history_keeps_seven_executed_actions_and_current_candidate_separate(self):
        history = [{'role': 'user', 'content': 'task'}]
        for n in range(10):
            history.extend([{'role': 'agent', 'thought': f'thought_{n}',
                             'action': json.dumps({'name': 'read', 'arguments': {'n': n}})},
                            {'role': 'environment', 'content': f'prior_result_{n}'}])
        state, action, _, _ = recorded_state(Review(tuple(history), 'task', {'name': 'next'}), self.author)
        self.assertEqual(state['total_executed_steps'], 10)
        self.assertEqual(len([m for m in state['conversation_history'] if m['role'] == 'assistant']), 7)
        self.assertNotIn('thought_0', json.dumps(state['conversation_history']))
        self.assertIn('prior_result_9', state['axtree_txt'])
        self.assertNotIn('"next"', json.dumps(state['conversation_history']))

    def test_malformed_or_unknown_policy_response_does_not_fail_open(self):
        for response in ['{}', forecast(['P999'])]:
            transport = Transport(response)
            guard = AuthorSafePred(self.author, transport, self.policies)
            with self.assertRaises(GuardError):
                guard.review(self.context())
            # Native _simulate_api retries malformed formats three times per root call.
            self.assertEqual(len(guard.capture['calls']), 6 if response == '{}' else 2)

    def test_invalid_next_review_does_not_reuse_previous_capture(self):
        guard = AuthorSafePred(self.author, Transport(forecast([])), self.policies)
        guard.review(self.context())
        self.assertTrue(guard.capture)
        with self.assertRaises(GuardError):
            guard.review(Review((), candidate=None))
        self.assertEqual(guard.capture, {})

    def test_context_budget_preserves_policy_task_and_candidate(self):
        transport = Transport(forecast([]))
        world = author_world(self.author, transport)
        state, action, tools, _ = recorded_state(self.context(), self.author)
        state['axtree_txt'] = tools
        transport.input_limit = transport.count_prompt(world._create_prompt(state, action, policies=self.policies)) + 160
        observation = 'large observation ' * 1000
        state['axtree_txt'] = tools + observation
        fitted, budget = fit_state(world, transport, state, action, self.policies, tools, observation)
        prompt = world._create_prompt(fitted, action, policies=self.policies)
        self.assertLessEqual(transport.count_prompt(prompt), transport.input_limit)
        self.assertTrue(budget['input_truncated'])
        self.assertEqual(fitted['current_action_reasoning'], state['current_action_reasoning'])
        self.assertIn('Do not disclose private credentials.', prompt)
        self.assertIn('Read the document', prompt)

    def test_policy_extraction_runs_author_validation_dedup_and_goal_alignment(self):
        rule = copy.deepcopy(self.policies[1])
        transport = Transport(json.dumps([rule, rule]))
        result = extract_policies(self.author, transport, 'Published benchmark policy definitions.')
        self.assertEqual(result[0]['policy_id'], 'P000')
        self.assertEqual(len(result), 2)
        self.assertIn('Published benchmark policy definitions.', transport.calls[0]['prompt'])


if __name__ == '__main__':
    unittest.main()
