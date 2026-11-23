from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agentguard.replay_classification import cohort_labels,compare,load_run,metrics


def source():
    return [{'case_key':key,'stage':stage,'attack_success':success,'utility':1} for key,stage,success in
            [('p1','under_attack',1),('p2','under_attack',1),('n','benign',None),('u','under_attack',0)]]


def record(row,prediction,status='ok'):
    return {'record_type':'case','case_key':row['case_key'],'stage':row['stage'],
            'source_attack_success':row['attack_success'],'source_utility':row['utility'],
            'status':status,'prediction':prediction if status=='ok' else None,
            'events':[{'decision':('BLOCK' if prediction else 'ALLOW') if status=='ok' else 'ERROR',
                       'latency_seconds':.2}]}


class ClassificationTests(unittest.TestCase):
    def test_failed_attack_is_unlabeled_not_a_safety_negative(self):
        labels,excluded=cohort_labels(source())
        self.assertEqual(labels,{'p1':1,'p2':1,'n':0})
        self.assertEqual(excluded,['u'])

    def test_all_methods_share_valid_ids_and_pending_does_not_reduce_scope(self):
        rows=source()
        runs={'a':{'status':'complete_verified','records':[record(r,1,'error' if r['case_key']=='p2' else 'ok') for r in rows]},
              'b':{'status':'complete_verified','records':[record(r,1) for r in rows]},
              'pending':{'status':'pending','records':[record(rows[0],1)]}}
        report=compare(rows,runs)
        self.assertEqual(report['common_case_keys'],['n','p1'])
        self.assertEqual(report['common_excluded_invalid_case_keys'],['p2'])
        self.assertNotIn('pending',report['methods'])
        self.assertEqual(report['methods']['a']['total_cases'],report['methods']['b']['total_cases'])
        self.assertEqual(report['methods']['b']['balanced_accuracy'],.5)
        self.assertEqual(report['coverage']['a']['errors'],1)

    def test_high_positive_prevalence_makes_always_intervene_f1_high(self):
        labels={str(i):int(i<9) for i in range(10)}
        records=[{'case_key':key,'prediction':1,'events':[]} for key in labels]
        result=metrics(records,labels)
        self.assertGreater(result['f1'],.94)
        self.assertEqual((result['recall'],result['fpr'],result['balanced_accuracy']),(1.,1.,.5))

    def test_saved_error_is_not_converted_into_a_safety_prediction(self):
        with TemporaryDirectory() as d:
            path=Path(d);row=source()[0];r=record(row,0,'error');r['prediction']=0
            meta={'record_type':'run_metadata','method':'agentdog','bundle_sha256':'bundle'}
            (path/'results.jsonl').write_text('\n'.join(json.dumps(x) for x in [meta,r]))
            with self.assertRaisesRegex(ValueError,'Error verdict'):
                load_run('agentdog',path,'bundle',{row['case_key']:row})

    def test_source_outcome_changes_and_tampered_verified_files_are_rejected(self):
        with TemporaryDirectory() as d:
            path=Path(d);row=source()[0];r=record(row,1)
            meta={'record_type':'run_metadata','method':'agentdog','bundle_sha256':'bundle'}
            result=path/'results.jsonl'
            result.write_text('\n'.join(json.dumps(x) for x in [meta,r,{'record_type':'overall_summary'}]))
            (path/'verification.json').write_text(json.dumps({'status':'complete_verified','results_sha256':'wrong'}))
            with self.assertRaisesRegex(ValueError,'hash'):
                load_run('agentdog',path,'bundle',{row['case_key']:row})
            (path/'verification.json').write_text(json.dumps({'status':'complete_verified',
                'results_sha256':sha256(result.read_bytes()).hexdigest()}))
            changed={**row,'attack_success':0}
            with self.assertRaisesRegex(ValueError,'Source outcome'):
                load_run('agentdog',path,'bundle',{row['case_key']:changed})


if __name__=='__main__':unittest.main()
