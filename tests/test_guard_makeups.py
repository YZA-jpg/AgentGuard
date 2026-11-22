import copy
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agentguard.guard import Decision, GuardError, Verdict, json_text
from agentguard.native_replay import evaluate_case, summarize
from agentguard.replay_makeup import prepare, merge
from agentguard.safetydrift_data import SafetyCase, reviews
from agentguard.shieldagent_safetydrift import prompt_for, verify_records, summary_for
from agentguard.safetydrift_eval import evaluate_case as safety_evaluate
from test_native_replay import fixture, TOOLS


class Dog:
    def __init__(self, fail=False): self.fail=fail
    def reset(self): pass
    def review(self, context):
        if self.fail: raise GuardError('missing judgment')
        return Verdict(Decision.BLOCK, details={'raw_output':'<Judgment>unsafe</Judgment>'})


class MakeupTests(unittest.TestCase):
    def setup_run(self, root):
        cases=[{'case_key':key,'suite':'s','stage':'benign','utility':1,
                'attack_success':None,'messages':fixture()} for key in ('good','bad')]
        bundle={'metadata':{'cases':2},'cases':cases,'tools':{'s':list(TOOLS)}}
        path=root/'bundle.json'; path.write_text(json_text(bundle))
        metadata={'record_type':'run_metadata','method':'agentdog','stage':'formal',
                  'bundle_sha256':sha256(path.read_bytes()).hexdigest(),
                  'guard':{'max_new_tokens':1024},'implementation_sha256':{}}
        records=[evaluate_case(c,TOOLS,Dog(c['case_key']=='bad')) for c in cases]
        parent=root/'parent';parent.mkdir()
        self.save(parent,metadata,records)
        return path,parent,metadata,records,cases

    def save(self,path,metadata,records):
        (path/'results.jsonl').write_text('\n'.join(json_text(x) for x in [metadata,*records,summarize(records)])+'\n')

    def test_retry_only_errors_and_merge_preserves_success_and_original(self):
        with TemporaryDirectory() as d:
            root=Path(d);bundle,parent,meta,old,cases=self.setup_run(root)
            old_hash=sha256((parent/'results.jsonl').read_bytes()).hexdigest()
            plan=prepare(bundle,parent,root/'plan')
            self.assertEqual(plan['retry_case_keys'],['bad'])
            subset=json.loads((root/'plan/bundle.json').read_text())
            self.assertEqual(subset['metadata']['cases'],1)
            retry=root/'retry';retry.mkdir();retry_meta=copy.deepcopy(meta)
            retry_meta['bundle_sha256']=sha256((root/'plan/bundle.json').read_bytes()).hexdigest()
            self.save(retry,retry_meta,[evaluate_case(cases[1],TOOLS,Dog())])
            result=merge(bundle,parent,root/'plan',retry,root/'merged')
            self.assertEqual(result['error_cases'],0)
            new=[json.loads(x) for x in (root/'merged/results.jsonl').read_text().splitlines()]
            self.assertEqual(new[1],old[0])
            self.assertEqual(old_hash,sha256((parent/'results.jsonl').read_bytes()).hexdigest())

    def test_changed_source_or_generation_config_cannot_be_merged(self):
        with TemporaryDirectory() as d:
            root=Path(d);bundle,parent,meta,old,cases=self.setup_run(root)
            prepare(bundle,parent,root/'plan')
            retry=root/'retry';retry.mkdir();meta=copy.deepcopy(meta)
            meta['bundle_sha256']=sha256((root/'plan/bundle.json').read_bytes()).hexdigest()
            meta['guard']['max_new_tokens']=2048
            self.save(retry,meta,[evaluate_case(cases[1],TOOLS,Dog())])
            with self.assertRaisesRegex(ValueError,'guard configuration'):
                merge(bundle,parent,root/'plan',retry,root/'merged')
            bundle.write_text(bundle.read_text()+' ')
            with self.assertRaisesRegex(ValueError,'bundle hash'):
                prepare(bundle,parent,root/'other')

    def test_successful_cases_cannot_be_replaced_and_errors_remain_errors(self):
        with TemporaryDirectory() as d:
            root=Path(d);bundle,parent,meta,old,cases=self.setup_run(root)
            prepare(bundle,parent,root/'plan')
            retry=root/'retry';retry.mkdir();meta=copy.deepcopy(meta)
            meta['bundle_sha256']=sha256((root/'plan/bundle.json').read_bytes()).hexdigest()
            self.save(retry,meta,[evaluate_case(cases[0],TOOLS,Dog())])
            with self.assertRaisesRegex(ValueError,'failed case IDs'):
                merge(bundle,parent,root/'plan',retry,root/'wrong')
            self.save(retry,meta,[evaluate_case(cases[1],TOOLS,Dog(True))])
            result=merge(bundle,parent,root/'plan',retry,root/'still-error')
            self.assertEqual(result['error_cases'],1)
            self.assertEqual(json.loads((root/'still-error/verification.json').read_text())['status'],
                             'complete_with_errors_verified')


class ShieldSafetyTests(unittest.TestCase):
    @staticmethod
    def author():
        return {'create_ipt':lambda dialog,environment,model:dialog+'\n'+environment,
                'format_resp':lambda text:'unsafe' if text=='[Answer]unsafe' else 'safe'}

    @staticmethod
    def tokenizer(text,**kwargs): return {'input_ids':list(text.encode())}

    def case(self):
        return SafetyCase('x','category',1,1,'task',TOOLS,(
            {'candidate':{'name':'read','arguments':{'path':'a'}},'thought':'inspect',
             'observation':'OWN_FUTURE_RESULT'},
            {'candidate':{'response':'finish'},'thought':'','observation':'LATER_RESULT'}))

    def test_author_prompt_contains_current_candidate_without_own_result(self):
        first=next(reviews(self.case()));prompt=prompt_for(self.author(),first)
        self.assertIn('SafetyDrift',prompt);self.assertIn('tool_arguments',prompt)
        self.assertNotIn('OWN_FUTURE_RESULT',prompt)
        self.assertNotIn('LATER_RESULT',prompt)
        self.assertNotIn('first_hazard',prompt)
        self.assertNotIn('risk_level',prompt)

    def test_verifier_checks_saved_decision_and_causal_input(self):
        author=self.author();tokenizer=self.tokenizer
        class Guard:
            def reset(self): self.capture={}
            def review(self,context):
                prompt=prompt_for(author,context);ids=tokenizer(prompt)['input_ids']
                self.capture={'raw_output':'[Answer]unsafe','prompt_sha256':sha256(prompt.encode()).hexdigest(),
                    'input_sha256':sha256(json_text(ids).encode()).hexdigest(),'input_tokens':len(ids),
                    'full_input_tokens':len(ids),'input_truncated':False,'output_tokens':3}
                return Verdict(Decision.BLOCK,details=dict(self.capture))
        case=self.case();record=safety_evaluate(case,Guard())
        summary=summary_for([record])
        self.assertEqual(verify_records([record],[case],summary,author,tokenizer,10000)['cases'],1)
        changed=copy.deepcopy(record);changed['reviews'][0]['decision']='ALLOW'
        with self.assertRaises(ValueError):
            verify_records([changed],[case],summary,author,tokenizer,10000)
        changed=copy.deepcopy(record);changed['reviews'][0]['input']['history']+=({'role':'environment','content':'future'},)
        with self.assertRaisesRegex(ValueError,'visible input'):
            verify_records([changed],[case],summary,author,tokenizer,10000)


if __name__=='__main__': unittest.main()
