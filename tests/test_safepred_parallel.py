import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from agentguard.safepred_parallel import (case_seed,make_jobs,read_records,collect_records,
                                         gpu_requirements,validate_shard,execute_plan)

ROOT=Path(__file__).resolve().parents[1]
POLICY=ROOT/'results/safepred-policy-v2-preflight-20261124/safetydrift-policy'


class ParallelTests(unittest.TestCase):
    def test_case_seed_and_job_assignment_are_stable_across_modes(self):
        rows=[{'case_id':'a'},{'case_id':'b'}]
        jobs=make_jobs(rows,['legacy','memory-tools'],2)
        self.assertEqual(len({r['job_key'] for r in jobs}),4)
        self.assertEqual(case_seed('safetydrift','a'),case_seed('safetydrift','a'))
        self.assertNotEqual(case_seed('safetydrift','a'),case_seed('safetydrift','b'))
        self.assertEqual({r['case_id'] for r in jobs if r['worker']==0},{'a','b'})
        with self.assertRaisesRegex(ValueError,'Duplicate case IDs'):
            make_jobs([{'case_id':'a'},{'case_id':'a'}],['legacy'],2)

    def test_partial_tail_is_preserved_before_resume_truncation(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'shard.jsonl'
            first=json.dumps({'job_key':'a'})+'\n'
            path.write_bytes(first.encode()+b'{"job_key":')
            with self.assertRaisesRegex(ValueError,'partial'):
                read_records(path)
            rows=read_records(path,repair_tail=True)
            self.assertEqual(rows,[{'job_key':'a'}])
            self.assertEqual(path.read_bytes(),first.encode())
            self.assertTrue(list(path.parent.glob('shard.jsonl.partial-*')))

    def test_collection_rejects_duplicate_missing_or_unknown_jobs(self):
        jobs=[{'job_key':'a'},{'job_key':'b'}]
        with self.assertRaisesRegex(ValueError,'Missing'):
            collect_records(jobs,[[{'job_key':'a'}]])
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            collect_records(jobs,[[{'job_key':'a'},{'job_key':'a'},{'job_key':'b'}]])
        with self.assertRaisesRegex(ValueError,'Unknown'):
            collect_records(jobs,[[{'job_key':'x'}]])

    def test_same_gpu_requires_aggregate_memory_not_one_copy_budget(self):
        self.assertEqual(gpu_requirements(['4','4']),{'4':56000})
        self.assertEqual(gpu_requirements(['0','1']),{'0':28000,'1':28000})

    def test_record_cannot_change_its_arm_or_worker_or_case(self):
        job={'job_key':'memory::a','case_id':'a','mode':'memory','worker':0}
        for field,value in [('case_id','b'),('mode','legacy'),('worker',1)]:
            altered={**job,field:value}
            with self.assertRaisesRegex(ValueError,'metadata'):
                collect_records([job],[[altered]])
            with self.assertRaisesRegex(ValueError,'metadata'):
                validate_shard([job],[altered])

    def test_resume_counts_only_new_cases_and_merges_in_plan_order(self):
        with TemporaryDirectory() as tmp:
            directory=Path(tmp)
            jobs=make_jobs([{'case_id':'a'},{'case_id':'b'}],['legacy'],1)
            (directory/'shard-0.jsonl').write_text(json.dumps(jobs[0])+'\n')
            plan={'gpus':['4'],'jobs':jobs,'modes':['legacy']}
            args=SimpleNamespace(resume=True,scope='calibration',benchmark='safetydrift',modes=['legacy'])
            def launch(*_args,**_kwargs):
                with (directory/'shard-0.jsonl').open('a') as stream:
                    stream.write(json.dumps(jobs[1])+'\n')
                return SimpleNamespace(wait=lambda:0,poll=lambda:0)
            def checked(_root,_directory,_plan,records):
                self.assertEqual([r['case_id'] for r in records],['a','b'])
                return {'status':'complete_verified'}
            with patch('agentguard.safepred_parallel.subprocess.check_output',return_value='81000'), \
                 patch('agentguard.safepred_parallel.subprocess.Popen',side_effect=launch), \
                 patch('agentguard.safepred_parallel.monotonic',side_effect=[100.,101.]), \
                 patch('agentguard.safepred_parallel.summarize',return_value={}), \
                 patch('agentguard.safepred_parallel.verify',side_effect=checked):
                self.assertEqual(execute_plan(args,directory,directory,plan,[{},{}],{'4':28000}),0)
            result=json.loads((directory/'summary.json').read_text())
            self.assertEqual(result['completed_jobs_this_session'],1)
            self.assertEqual(result['jobs_per_second_this_session'],1.)
            self.assertTrue((directory/'batch.done').exists())


@unittest.skipUnless((POLICY/'admission.json').exists() and (ROOT/'models/qwen3-8b-safepred').exists(),
                     'Admitted policies, original data and tokenizer not installed')
class NativeParallelRoundtripTests(unittest.TestCase):
    def test_shards_resume_and_cpu_verifier_reconstruct_native_inputs(self):
        from agentguard import safepred_parallel as runner
        from agentguard.safepred_policy_v2 import verify_admission
        from transformers import AutoTokenizer
        from test_safepred_author import forecast
        tokenizer=AutoTokenizer.from_pretrained(ROOT/'models/qwen3-8b-safepred',local_files_only=True)
        class Transport:
            max_tokens=4000
            input_limit=36960
            constructions=0
            def __init__(self,*_args):
                type(self).constructions+=1
                self.calls=[]
                self.torch=SimpleNamespace(manual_seed=lambda _seed:None)
                self.model=SimpleNamespace(dtype='bfloat16',config=SimpleNamespace(max_position_embeddings=40960),
                                           generation_config=SimpleNamespace(to_dict=lambda:{}))
            def encode(self,text):return tokenizer.encode(text,add_special_tokens=False)
            def decode(self,ids):return tokenizer.decode(ids,skip_special_tokens=False)
            def count_prompt(self,prompt):
                return len(tokenizer.apply_chat_template([{'role':'user','content':prompt}],tokenize=True,
                            add_generation_prompt=True,enable_thinking=False,return_dict=False))
            def generate(self,prompt,**_kwargs):
                response=forecast([])
                self.calls.append({'prompt':prompt,'response':response,'input_tokens':self.count_prompt(prompt),
                                   'output_tokens':len(self.encode(response)),'latency_seconds':.01,
                                   'generation_limit_reached':False})
                return response
        admission=verify_admission(POLICY,ROOT/'policies/specs/safepred-v2/safetydrift.json','safetydrift')
        cases,identity=runner.load_cases(ROOT,'safetydrift','calibration',2,Path('unused'))
        modes=['legacy','memory','tools','memory-tools']
        plan={'protocol':runner.PROTOCOL,'benchmark':'safetydrift','scope':'calibration','limit':2,
              'bundle':'unused','modes':modes,'gpus':['0','1'],'data_identity':identity,
              'case_ids':[c['case_id'] for c in cases],'policy_dir':str(POLICY),
              'policy_sha256':admission['policy_sha256'],'jobs':make_jobs(cases,modes,2),
              'code_hashes':{name:runner.digest(ROOT/'agentguard'/name) for name in runner.CODE_FILES},
              'verifier_sha256':runner.digest(ROOT/'scripts/verify-safepred-author.py')}
        with TemporaryDirectory(dir=ROOT/'cache/tmp') as tmp:
            directory=Path(tmp)
            runner.write_json(directory/'plan.json',plan)
            with patch('agentguard.safepred_author.TransformersTransport',Transport):
                for index in (0,1):self.assertEqual(runner.worker(ROOT,directory,index),0)
                before=[runner.digest(directory/f'shard-{i}.jsonl') for i in (0,1)]
                for index in (0,1):self.assertEqual(runner.worker(ROOT,directory,index),0)
                self.assertEqual(Transport.constructions,2)
                self.assertEqual(before,[runner.digest(directory/f'shard-{i}.jsonl') for i in (0,1)])
            records=collect_records(plan['jobs'],[read_records(directory/f'shard-{i}.jsonl') for i in (0,1)])
            summary={'cases_across_arms':len(records),'case_count_per_arm':len(cases),
                     'methods':{m:runner.summarize([r for r in records if r['mode']==m],'safetydrift') for m in modes}}
            runner.write_json(directory/'summary.json',summary)
            self.assertEqual(runner.verify(ROOT,directory,plan,records)['status'],'complete_verified')
            summary['methods']['legacy']['f1']=.99
            runner.write_json(directory/'summary.json',summary)
            with self.assertRaisesRegex(ValueError,'Summary differs'):
                runner.verify(ROOT,directory,plan,records)


if __name__=='__main__':
    unittest.main()
