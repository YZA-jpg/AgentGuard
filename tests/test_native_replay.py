import copy
from dataclasses import asdict
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agentguard.guard import Decision,Verdict,json_text
from agentguard.native_replay_data import recorded_reviews,smoke_cases
from agentguard.native_replay import evaluate_case,summarize,verify


TOOLS=({'name':'read','description':'read','parameters':{}},)


def fixture():
    def call(identifier):return {'id':identifier,'function':'read','args':{'path':identifier},'placeholder_args':None}
    first,second=call('a'),call('b')
    return [{'role':'system','content':[{'type':'text','content':'system'}]},
            {'role':'user','content':[{'type':'text','content':'task'}]},
            {'role':'assistant','content':[{'type':'text','content':'inspect'}],'tool_calls':[first,second]},
            {'role':'tool','tool_call_id':'a','tool_call':first,'content':[{'type':'text','content':'result-A'}]},
            {'role':'tool','tool_call_id':'b','tool_call':second,'content':[{'type':'text','content':'result-B'}]},
            {'role':'assistant','content':[{'type':'text','content':'FINAL-RESPONSE'}],'tool_calls':None}]


class NativeReplayTests(unittest.TestCase):
    def test_own_future_result_and_final_response_are_not_visible(self):
        first,second,last=list(recorded_reviews(fixture(),TOOLS))
        self.assertNotIn('result-A',json_text(asdict(first[1])))
        self.assertNotIn('result-B',json_text(asdict(first[1])))
        self.assertNotIn('FINAL-RESPONSE',json_text(asdict(first[1])))
        self.assertIn('result-A',json_text(asdict(second[1])))
        self.assertNotIn('result-B',json_text(asdict(second[1])))
        self.assertEqual(last[1].candidate,{'response':'FINAL-RESPONSE'})
        self.assertIn('result-B',json_text(asdict(last[1])))

    def test_changed_future_does_not_change_current_input(self):
        messages=fixture();before=next(recorded_reviews(messages,TOOLS))[1]
        messages[3]['content'][0]['content']='CHANGED_FUTURE'
        messages[-1]['content'][0]['content']='CHANGED_FINAL'
        self.assertEqual(asdict(before),asdict(next(recorded_reviews(messages,TOOLS))[1]))

    def test_pending_unexecuted_proposals_are_not_audited(self):
        messages=fixture()[:3]
        self.assertEqual(list(recorded_reviews(messages,TOOLS)),[])

    def test_mismatched_results_are_rejected(self):
        messages=fixture();messages[3]['tool_call_id']='wrong'
        with self.assertRaisesRegex(ValueError,'ID mismatch'):list(recorded_reviews(messages,TOOLS))

    def test_each_case_resets_state_and_stops_on_first_intervention(self):
        class Guard:
            def __init__(self):self.resets=0;self.calls=0
            def reset(self):self.resets+=1;self.calls=0
            def review(self,context):self.calls+=1;return Verdict(Decision.BLOCK)
        guard=Guard()
        row={'case_key':'x','suite':'s','stage':'under_attack','utility':0,'attack_success':1,'messages':fixture()}
        for _ in range(2):
            record=evaluate_case(row,TOOLS,guard)
            self.assertEqual(len(record['events']),1);self.assertEqual(record['first_intervention'],0)
        self.assertEqual(guard.resets,2)

    def test_metrics_do_not_invent_attack_safety_labels_or_asr(self):
        def row(stage,success,pred):
            return {'stage':stage,'source_attack_success':success,'prediction':pred,'status':'ok',
                    'events':[{'decision':'BLOCK' if pred else 'ALLOW','latency_seconds':.2,'details':{}}]}
        result=summarize([row('benign',None,1),row('under_attack',1,1),row('under_attack',0,0)])
        self.assertEqual(result['source_successful_attacks']['intervention_rate'],1.)
        self.assertEqual(result['attacked']['intervention_rate'],.5)
        for key in ('f1','recall','fpr','asr','utility'):self.assertIsNone(result[key])

    def test_smoke_selection_does_not_depend_on_attack_outcomes(self):
        rows=[{'case_key':f'{suite}-{stage}-{i}','suite':suite,'stage':stage,'attack_success':i%2}
              for suite in ('workspace','slack','travel','banking') for stage in ('benign','under_attack') for i in range(4)]
        keys=[r['case_key'] for r in smoke_cases(rows)]
        for row in rows:row['attack_success']=1-row['attack_success']
        self.assertEqual(keys,[r['case_key'] for r in smoke_cases(rows)])
        self.assertEqual(len(keys),8)

    def test_saved_prefix_verifier_detects_tampering(self):
        class Guard:
            info={}
            def reset(self):pass
            def review(self,context):return Verdict(Decision.BLOCK,details={'raw_output':'<Judgment>unsafe</Judgment>'})
        row={'case_key':'x','suite':'s','stage':'benign','utility':1,'attack_success':None,'messages':fixture()}
        record=evaluate_case(row,TOOLS,Guard())
        bundle={'cases':[row],'tools':{'s':list(TOOLS)}}
        metadata={'record_type':'run_metadata','method':'agentdog','stage':'formal'}
        with TemporaryDirectory() as directory:
            path=Path(directory)
            def save():
                values=[metadata,record,summarize([record])]
                (path/'results.jsonl').write_text('\n'.join(json_text(v) for v in values)+'\n')
            save();self.assertEqual(verify(path,bundle)['cases'],1)
            record['events'][0]['visible_review_sha256']='tampered';save()
            with self.assertRaisesRegex(ValueError,'future information'):verify(path,bundle)


if __name__=='__main__':unittest.main()
