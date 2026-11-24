import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from dataclasses import asdict

from agentguard.safepred_policy_v2 import (load_spec, render_source, coverage_report, contract_passed,
                                         file_hash, verify_admission, VERSION)
from agentguard.safepred_policy_contracts import contracts
from agentguard.safepred_author import AUTHOR_REVISION, MODEL_REVISION

ROOT = Path(__file__).resolve().parents[1]


class PolicyV2Tests(unittest.TestCase):
    def spec(self, name='safetydrift'):
        return load_spec(ROOT/'policies/specs/safepred-v2'/f'{name}.json', name)

    def policies(self, spec):
        return [{'policy_id': 'P000', 'policy_description': 'Actions must align with the task.'}] + [
            {'policy_id': f'P{i:03}', 'policy_description': c['obligation'], 'scope': c['scope']}
            for i, c in enumerate(spec['clauses'], 1)]

    def test_old_labeling_description_is_rejected(self):
        spec = self.spec()
        old = json.loads((ROOT/'policies/frozen/safepred-author-qwen3-8b-20261120/safetydrift.json').read_text())
        report = coverage_report(spec, old)
        self.assertFalse(report['passed'])
        self.assertEqual(len(report['missing_controls']), len(spec['clauses']))

    def test_coverage_uses_normative_descriptions_not_definitions_or_p000(self):
        spec = self.spec()
        policies = self.policies(spec)
        self.assertTrue(coverage_report(spec, policies)['passed'])
        policies[1]['definitions'] = [policies[1]['policy_description']]
        policies[1]['policy_description'] = 'The dataset labels network communications.'
        self.assertIn('SD-NETWORK', coverage_report(spec, policies[:2])['missing_controls'])

    def test_policy_source_never_serializes_fixture_or_gold_extras(self):
        spec = self.spec()
        changed = copy.deepcopy(spec)
        changed['fixtures'] = {'label': 'SECRET_FIXTURE_LABEL'}
        changed['test_trajectories'] = 'SECRET_TEST_OUTCOME'
        self.assertEqual(render_source(spec), render_source(changed))
        self.assertNotIn('SECRET', render_source(changed))
        with self.assertRaises(ValueError):
            load_spec(ROOT/'policies/specs/safepred-v2/safetydrift.json', 'agentdojo')

    def test_unsafe_contract_requires_relevant_policy_not_goal_alignment_only(self):
        coverage = {'coverage': {'control': ['P001']}}
        fixture = {'expected': 'BLOCK', 'control': 'control'}
        self.assertFalse(contract_passed(fixture, 'BLOCK', ['P000'], coverage))
        self.assertTrue(contract_passed(fixture, 'BLOCK', ['P001'], coverage))
        self.assertFalse(contract_passed({'expected': 'ALLOW'}, 'BLOCK', [], coverage))

    def admitted_fixture(self, directory):
        spec_path = ROOT/'policies/specs/safepred-v2/safetydrift.json'
        spec = self.spec()
        policies = self.policies(spec)
        coverage = coverage_report(spec, policies)
        (directory/'source.txt').write_text(render_source(spec), encoding='utf8')
        checks = [{**{k: f[k] for k in ('id', 'control', 'expected')}, 'context': asdict(f['context']),
                   'passed': True, 'decision': f['expected'],
                   'violated_policy_ids': coverage['coverage'][f['control']][:1] if f['expected'] == 'BLOCK' else []}
                  for f in contracts('safetydrift')]
        for name, value in (('policies', policies), ('contracts', checks), ('coverage', coverage), ('extraction', {})):
            (directory/f'{name}.json').write_text(json.dumps(value), encoding='utf8')
        admission = {'status': 'admitted', 'version': VERSION, 'benchmark': 'safetydrift',
                     'author_revision': AUTHOR_REVISION, 'model_revision': MODEL_REVISION,
                     'test_trajectories_or_labels_used': False, 'spec_sha256': file_hash(spec_path),
                     'implementation_hashes': {name: file_hash(ROOT/'agentguard'/name)
                                               for name in ('safepred_policy_v2.py', 'safepred_policy_contracts.py')}}
        for key, name in (('source', 'source.txt'), ('policy', 'policies.json'), ('contracts', 'contracts.json'),
                          ('coverage', 'coverage.json'), ('extraction', 'extraction.json')):
            admission[key+'_sha256'] = file_hash(directory/name)
        (directory/'admission.json').write_text(json.dumps(admission), encoding='utf8')
        return spec_path, admission

    def test_admission_rejects_changed_policy_before_evaluation(self):
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            spec, _ = self.admitted_fixture(directory)
            self.assertEqual(verify_admission(directory, spec, 'safetydrift')['status'], 'admitted')
            (directory/'policies.json').write_text('[]')
            with self.assertRaisesRegex(ValueError, 'artifact changed'):
                verify_admission(directory, spec, 'safetydrift')

    def test_missing_contract_rejected_even_if_its_file_checksum_is_updated(self):
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            spec, admission = self.admitted_fixture(directory)
            rows = json.loads((directory/'contracts.json').read_text())[:-1]
            (directory/'contracts.json').write_text(json.dumps(rows))
            admission['contracts_sha256'] = file_hash(directory/'contracts.json')
            (directory/'admission.json').write_text(json.dumps(admission))
            with self.assertRaisesRegex(ValueError, 'Missing or duplicate'):
                verify_admission(directory, spec, 'safetydrift')


@unittest.skipUnless((ROOT/'vendor/SafePred-official/.git').exists(), 'Pinned author checkout not installed')
class NativePolicyContractTests(unittest.TestCase):
    def test_native_core_goal_only_outputs_cannot_admit_benchmark_controls(self):
        from agentguard.safepred_author import load_author
        from agentguard.safepred_policy_v2 import run_contracts
        from test_safepred_author import Transport, forecast
        spec = load_spec(ROOT/'policies/specs/safepred-v2/safetydrift.json', 'safetydrift')
        policies = [{'policy_id': 'P000', 'policy_description': 'Actions must align with the task.'}] + [
            {'policy_id': f'P{i:03}', 'policy_description': c['obligation'], 'scope': c['scope'], 'risk_level': 'high'}
            for i, c in enumerate(spec['clauses'], 1)]
        coverage = coverage_report(spec, policies)
        checks = run_contracts(spec, load_author(ROOT/'vendor/SafePred-official'),
                               Transport(forecast(['P000'])), policies, coverage)
        positive = [row for row in checks if row['expected'] == 'BLOCK']
        self.assertTrue(all(row['decision'] == 'BLOCK' for row in positive))
        self.assertTrue(all(not row['passed'] for row in positive))

if __name__ == '__main__':
    unittest.main()
