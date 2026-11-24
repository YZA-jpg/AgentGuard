import copy
import unittest

from agentguard.agentdog_recovery import repetitive_suffix,recovery_eligible,merge_recovery
from agentguard.dream_transfer import disjoint_calibration,validate_domain


class RecoveryTests(unittest.TestCase):
    def test_loop_detector_does_not_treat_short_legitimate_numbers_as_degenerate(self):
        self.assertTrue(repetitive_suffix('analysis '+ '12'*150))
        self.assertFalse(repetitive_suffix('account ending 12121212'))
        self.assertFalse(repetitive_suffix('normal coherent analysis and a valid conclusion'))

    def test_valid_judgment_never_triggers_recovery(self):
        bad={'decision':'ERROR','details':{'generation':{'raw_output':'analysis '+'12'*150}}}
        self.assertTrue(recovery_eligible(bad))
        good=copy.deepcopy(bad);good['details']['generation']['raw_output']='<Judgment>unsafe</Judgment>'+'12'*150
        self.assertFalse(recovery_eligible(good))

    def test_merge_only_failed_case_and_preserves_successful_records(self):
        old=[{'case_key':'good','status':'ok','prediction':0},{'case_key':'bad','status':'error','prediction':None}]
        before=copy.deepcopy(old)
        merged=merge_recovery(old,{'case_key':'bad','status':'ok','prediction':1})
        self.assertEqual(merged[0],old[0]);self.assertEqual(old,before)
        with self.assertRaises(ValueError):merge_recovery(old,{'case_key':'good','status':'ok'})


class TransferTests(unittest.TestCase):
    def row(self,key,split,text,label):
        return {'id':key,'dataset':'atbench','split':split,'task':text,'observations':[''],
                'actions':['act'],'successors':[],'label':label,'first_hazard':None}

    def test_calibration_duplicates_removed_without_reading_test_labels(self):
        cal=[self.row('c1','calibration','duplicate',0),self.row('c2','calibration','unique',1)]
        test=[self.row('t','heldout','duplicate',0)]
        kept,removed=disjoint_calibration(cal,test)
        self.assertEqual([r['id'] for r in kept],['c2']);self.assertEqual(removed,['c1'])
        test[0]['label']=1
        self.assertEqual((kept,removed),disjoint_calibration(cal,test))

    def test_calibration_domain_and_test_scope_are_checked(self):
        artifact={'domain':'atbench','calibration_ids':['c'],'test_ids':['t']}
        validate_domain(artifact,'atbench',['t'])
        with self.assertRaises(ValueError):validate_domain(artifact,'agentdojo',['t'])
        with self.assertRaises(ValueError):validate_domain({**artifact,'test_ids':['c']},'atbench',['c'])


if __name__=='__main__':unittest.main()
