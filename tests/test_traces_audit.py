import unittest
from dataclasses import replace

from agentguard.safetydrift_data import SafetyCase
from agentguard.traces_audit import majority_baseline, prefix_hashes, scenario_partition, verify_records
from agentguard.safetydrift_data import reviews
from dataclasses import asdict


def case(name, category, label, task='task', observation='result'):
    return SafetyCase(name, category, label, None, task, (), (
        {'candidate': {'name': 'read', 'arguments': {'path': 'x'}}, 'thought': '', 'observation': observation},
        {'candidate': {'response': 'summary'}, 'thought': '', 'observation': 'later'},))


class TracesAuditTests(unittest.TestCase):
    def test_shortcut_fits_training_only_and_reports_unknown_groups(self):
        train = [case('a', 'mail', 1), case('b', 'code', 0)]
        test = [case('c', 'mail', 0), case('d', 'unknown', 0)]
        first = majority_baseline(train, test, lambda c: c.category)
        changed = majority_baseline(train, [replace(c, label=1) for c in test], lambda c: c.category)
        self.assertEqual(first['predictions'], changed['predictions'])
        self.assertEqual(first['unseen_groups'], 1)
        self.assertEqual(first['predictions'][0], 1)

    def test_prefix_hash_excludes_current_result_and_gold_label(self):
        original = case('a', 'mail', 0)
        changed = case('b', 'mail', 1, observation='SECRET_CURRENT_RESULT')
        self.assertEqual(prefix_hashes(original)[0], prefix_hashes(changed)[0])
        self.assertNotEqual(prefix_hashes(original)[1], prefix_hashes(changed)[1])

    def test_scenario_partition_is_disjoint_and_does_not_use_labels(self):
        rows = [case(str(i), category, i % 2) for category in ('mail', 'code') for i in range(10)]
        # Distinct IDs are needed across categories; group multiple runs of the same scenario.
        rows = [replace(c, case_id=c.category + c.case_id) for c in rows]
        scenarios = {c.case_id: c.category + str(int(c.case_id[len(c.category):]) // 2) for c in rows}
        groups = scenario_partition(rows, scenarios)
        other = scenario_partition([replace(c, label=1-c.label) for c in rows], scenarios)
        self.assertEqual(groups, other)
        sets = [{scenarios[i] for i in ids} for ids in groups.values()]
        self.assertTrue(all(not sets[i] & sets[j] for i in range(3) for j in range(i)))
        self.assertEqual(set().union(*map(set, groups.values())), set(scenarios))

    def test_replay_verification_rejects_future_input_and_incomplete_pass_trajectory(self):
        row = case('a', 'mail', 0)
        contexts = list(reviews(row))
        record = {'case_id': 'a', 'label': 0, 'first_hazard': None, 'status': 'ok', 'prediction': 0,
                  'first_intervention': None, 'reviews': [
                      {'step': i, 'input': asdict(c), 'decision': 'ALLOW', 'risk_score': .1, 'latency_seconds': 1.}
                      for i, c in enumerate(contexts)]}
        self.assertEqual(verify_records([record], [row], .8)['cases'], 1)
        record['reviews'].pop()
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            verify_records([record], [row], .8)
        record['reviews'][0]['input']['candidate'] = {'response': 'FUTURE_RESULT'}
        with self.assertRaisesRegex(ValueError, 'input differs'):
            verify_records([record], [row], .8)


if __name__ == '__main__':
    unittest.main()
