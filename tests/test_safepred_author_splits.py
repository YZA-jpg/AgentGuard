"""Regression coverage for the failed formal SafetyDrift selection path."""

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agentguard.safepred_author_eval import cases_for
from agentguard.safetydrift_data import SafetyCase


class AuthorSafetyDriftSplitTests(unittest.TestCase):
    def cases(self):
        return [SafetyCase('heldout-safe','category',0,None,'task',(),(
                    {'candidate':{'response':'inspect'},'thought':'','observation':'future-safe'},)),
                SafetyCase('heldout-unsafe','category',1,0,'task',(),(
                    {'candidate':{'name':'send','arguments':{}},'thought':'','observation':'future-unsafe'},))]

    def args(self,mode='formal',ids=None):
        return SimpleNamespace(benchmark='safetydrift',mode=mode,data_root=Path('source'),
                               split_manifest=Path('split.json'),case_id=ids or [])

    def test_formal_selects_actual_heldout_and_causal_reviews(self):
        def selected(root,manifest,split):
            # This reproduces the loader contract that previously raised KeyError.
            return {'heldout':self.cases()}[split], {}
        with patch('agentguard.safetydrift_data.selected_cases',side_effect=selected) as load:
            rows=cases_for(self.args())
        self.assertEqual([row['case_id'] for row in rows],['heldout-safe','heldout-unsafe'])
        self.assertEqual([row['label'] for row in rows],[0,1])
        self.assertEqual(rows[1]['first_hazard'],0)
        review=rows[1]['contexts'][0][1]
        self.assertNotIn('future-unsafe',str(review))
        self.assertEqual(load.call_args.args[2],'heldout')

    def test_smoke_stays_in_calibration_without_using_test_labels(self):
        def selected(root,manifest,split):
            return {'calibration':self.cases()}[split], {}
        with patch('agentguard.safetydrift_data.selected_cases',side_effect=selected):
            rows=cases_for(self.args('smoke'))
        self.assertEqual([row['label'] for row in rows],[0,1])

    def test_explicit_case_ids_cannot_escape_heldout(self):
        with patch('agentguard.safetydrift_data.selected_cases',return_value=(self.cases(),{})):
            with self.assertRaisesRegex(ValueError,'not in this evaluation split'):
                cases_for(self.args(ids=['train-only']))


if __name__=='__main__': unittest.main()
