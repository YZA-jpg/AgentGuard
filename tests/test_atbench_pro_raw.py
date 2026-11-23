import copy
from types import SimpleNamespace
import unittest

from agentguard.atbench_pro_raw import observed_record,make_prompt,parse_response,evaluate_one,summary_for,verify_records


def example():
    return {'id':1,'label':1,'risk_source':'GOLD_SOURCE','reason':'GOLD_REASON',
            'failure_mode':'GOLD_FAILURE','real_world_harm':'GOLD_HARM',
            'tool_used':[{'name':'read','description':'Read data','parameters':{'type':'object'},
                          '_source':'DATASET_SOURCE','_original_description':'OLD_DESCRIPTION'}],
            'contents':[[{'role':'user','content':'task'},{'role':'agent','thought':'inspect',
                         'action':'{"name":"read","arguments":{}}'}],
                        [{'role':'environment','content':'observed result'}]]}


class RawBaselineTests(unittest.TestCase):
    def test_raw_turn_groups_preserved_and_gold_removed(self):
        row=example();before=copy.deepcopy(row);payload=observed_record(row)
        self.assertEqual(set(payload),{'contents','tool_used'})
        self.assertEqual(payload['contents'],row['contents'])
        self.assertEqual(set(payload['tool_used'][0]),{'name','description','parameters'})
        prompt=make_prompt(row)
        for forbidden in ('GOLD_SOURCE','GOLD_REASON','GOLD_FAILURE','GOLD_HARM','DATASET_SOURCE','OLD_DESCRIPTION'):
            self.assertNotIn(forbidden,prompt)
        self.assertNotIn('<Analysis>',prompt);self.assertNotIn('<Judgment>',prompt)
        self.assertEqual(row,before)

    def test_parser_requires_one_unambiguous_label(self):
        self.assertEqual(parse_response('{"label":"unsafe","reason":"unauthorized"}'),1)
        self.assertEqual(parse_response('```json\n{"label":"safe","reason":"authorized"}\n```'),0)
        for text in ('unsafe','{"label":"safe","label":"unsafe"}',
                     '{"label":1}','{"label":"safe"} {"label":"unsafe"}'):
            with self.assertRaises(ValueError):parse_response(text)

    def client(self,text):
        test=self
        class Completions:
            def create(self,**kwargs):
                test.request=kwargs
                return SimpleNamespace(id='response',model='deepseek-v4-pro',usage=None,
                    choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content=text))])
        return SimpleNamespace(chat=SimpleNamespace(completions=Completions()))

    def test_request_keeps_model_sampling_budget_and_input(self):
        record=evaluate_one(example(),self.client('{"label":"unsafe","reason":"risk"}'),'deepseek-v4-pro',1024)
        self.assertEqual(record['status'],'ok');self.assertEqual(record['prediction'],1)
        self.assertEqual(self.request['temperature'],0)
        self.assertEqual(self.request['extra_body'],{'enable_thinking':False})
        self.assertEqual(self.request['max_tokens'],1024)
        self.assertNotIn('response_format',self.request)
        self.assertEqual(self.request['messages'],[{'role':'user','content':make_prompt(example())}])

    def test_parse_failure_remains_error_and_verifier_detects_changed_inputs(self):
        row=example();bad=evaluate_one(row,self.client('not a verdict'),'deepseek-v4-pro',1024)
        self.assertEqual(bad['status'],'parse_error');self.assertIsNone(bad['prediction'])
        self.assertEqual(summary_for([bad])['error_cases'],1)
        good=evaluate_one(row,self.client('{"label":"unsafe","reason":"risk"}'),'deepseek-v4-pro',1024)
        summary=summary_for([good])
        self.assertEqual(verify_records([good],[row],summary)['status'],'complete_verified')
        changed=copy.deepcopy(good);changed['prompt_sha256']='changed'
        with self.assertRaisesRegex(ValueError,'input'):
            verify_records([changed],[row],summary_for([changed]))


if __name__=='__main__':unittest.main()
