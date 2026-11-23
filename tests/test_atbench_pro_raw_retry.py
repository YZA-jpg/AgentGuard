import copy
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agentguard.atbench_pro_raw import evaluate_one
from agentguard.atbench_pro_raw_retry import pending_ids,merge_records,retry_one,error_details,load_parent
from agentguard.atbench_pro_raw import PLAIN_PROMPT,PROMPT_VERSION,summary_for
from test_atbench_pro_raw import example


class Fake429(Exception):
    status_code=429
    body={'error':{'code':'Throttling.RateQuota'}}
    response=SimpleNamespace(headers={'retry-after':'2','x-request-id':'request'})


class RetryTests(unittest.TestCase):
    def good(self,row):
        class Call:
            def create(self,**kwargs):
                return SimpleNamespace(id='id',model='deepseek-v4-pro',usage=None,
                    choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content='{"label":"safe","reason":"ok"}'))])
        return evaluate_one(row,SimpleNamespace(chat=SimpleNamespace(completions=Call())),'deepseek-v4-pro',1024)

    def test_only429_failures_selected_and_successes_unchanged(self):
        row=example();good=self.good(row);bad={**copy.deepcopy(good),'case_id':'2','status':'api_error','prediction':None,'http_status':429}
        old=[good,bad];before=copy.deepcopy(old)
        self.assertEqual(pending_ids(old),['2'])
        replacement={**copy.deepcopy(good),'case_id':'2'}
        merged=merge_records(old,{'2':replacement})
        self.assertEqual(merged[0],good);self.assertEqual(old,before)
        with self.assertRaisesRegex(ValueError,'successful'):
            merge_records(old,{'1':replacement})

    def test_rate_retry_is_bounded_and_uses_retry_after(self):
        row=example();calls=[];waits=[]
        class Call:
            def create(inner,**kwargs):
                calls.append(kwargs)
                if len(calls)==1:raise Fake429()
                return SimpleNamespace(id='id',model='deepseek-v4-pro',usage=None,
                    choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content='{"label":"safe","reason":"ok"}'))])
        client=SimpleNamespace(chat=SimpleNamespace(completions=Call()))
        result=retry_one(row,client,'deepseek-v4-pro',1024,max_retries=2,base_delay=1,sleep=waits.append)
        self.assertEqual(result['status'],'ok');self.assertEqual(len(calls),2)
        self.assertEqual(waits,[2.]);self.assertEqual(len(result['retry_attempts']),2)
        self.assertEqual(calls[0],calls[1])

    def test_nontransient_quota_and_parse_error_are_not_retried(self):
        class Quota(Fake429):body={'code':'insufficient_quota'}
        class Call:
            def create(self,**kwargs):raise Quota()
        waits=[];client=SimpleNamespace(chat=SimpleNamespace(completions=Call()))
        result=retry_one(example(),client,'deepseek-v4-pro',1024,max_retries=5,sleep=waits.append)
        self.assertEqual(len(result['retry_attempts']),1);self.assertEqual(waits,[])
        self.assertTrue(result['retry_stopped_for_quota'])
        self.assertEqual(error_details(Quota())['provider_error_code'],'insufficient_quota')
        class BadOutput:
            def create(self,**kwargs):
                return SimpleNamespace(id='id',model='deepseek-v4-pro',usage=None,
                    choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content='not JSON'))])
        client=SimpleNamespace(chat=SimpleNamespace(completions=BadOutput()))
        result=retry_one(example(),client,'deepseek-v4-pro',1024,max_retries=5,sleep=waits.append)
        self.assertEqual(result['status'],'parse_error')
        self.assertEqual(len(result['retry_attempts']),1);self.assertEqual(waits,[])

    def test_persistent429_has_a_finite_attempt_budget(self):
        class Call:
            def create(self,**kwargs):raise Fake429()
        waits=[];client=SimpleNamespace(chat=SimpleNamespace(completions=Call()))
        result=retry_one(example(),client,'deepseek-v4-pro',1024,max_retries=1,base_delay=1,sleep=waits.append)
        self.assertEqual(len(result['retry_attempts']),2)
        self.assertEqual(result['retry_stop_reason'],'retry_budget_exhausted')
        self.assertEqual(waits,[2.])

    def test_parent_prompt_change_is_rejected_before_any_api_request(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp);data=p/'data.json';split=p/'split.json'
            data.write_text('[]');split.write_text('{}');row=example();record=self.good(row)
            metadata={'variant':PROMPT_VERSION,'mode':'formal',
                'prompt_sha256':sha256(PLAIN_PROMPT.encode()).hexdigest(),
                'data_sha256':sha256(data.read_bytes()).hexdigest(),
                'split_sha256':sha256(split.read_bytes()).hexdigest()}
            def save():
                result=p/'results.jsonl'
                result.write_text('\n'.join(json.dumps(x) for x in [metadata,record,summary_for([record])]))
                (p/'verification.json').write_text(json.dumps({'results_sha256':sha256(result.read_bytes()).hexdigest()}))
            save()
            with patch('agentguard.atbench_pro_raw_retry.selected_rows',return_value=[row]):
                self.assertEqual(load_parent(p,data,split)[1],[record])
                metadata['prompt_sha256']='changed';save()
                with self.assertRaisesRegex(ValueError,'prompt'):
                    load_parent(p,data,split)


if __name__=='__main__':unittest.main()
