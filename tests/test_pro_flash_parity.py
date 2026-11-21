import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('pro_flash_parity',
    Path(__file__).resolve().parents[1]/'scripts/check-pro-flash-parity.py')
parity=importlib.util.module_from_spec(spec); spec.loader.exec_module(parity)


class ModelOnlyParityTests(unittest.TestCase):
    def configs(self):
        flash={'model':'deepseek-v4-flash-0731','temperature':0.,'thinking':'provider',
               'workers':4,'attack_model_name':'DeepSeek','runner_sha256':'old','base_url':'https://endpoint/v1'}
        return flash,{**flash,'model':'deepseek-v4-pro','runner_sha256':'new'}

    def test_backbone_and_runner_version_can_change_without_changing_protocol(self):
        flash,pro=self.configs(); parity.assert_model_only(flash,pro,endpoint=True)

    def test_temperature_thinking_or_attack_name_changes_are_rejected(self):
        flash,pro=self.configs()
        for key,value in [('temperature',None),('thinking','enabled'),('attack_model_name','Deepseek v4 Pro')]:
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'protocol differences'):
                parity.assert_model_only(flash,{**pro,key:value})

    def test_task_exclusion_changes_are_rejected(self):
        flash,pro=self.configs()
        with self.assertRaisesRegex(ValueError,'protocol differences'):
            parity.assert_model_only(flash,{**pro,'excluded_user_tasks':['slack:7']})

    def test_older_metadata_without_exclusions_matches_explicit_empty_list(self):
        flash,pro=self.configs()
        parity.assert_model_only(flash,{**pro,'excluded_user_tasks':[]})

    def test_actual_endpoint_change_is_rejected_after_smoke(self):
        flash,pro=self.configs()
        with self.assertRaisesRegex(ValueError,'endpoint differs'):
            parity.assert_model_only(flash,{**pro,'base_url':'https://other/v1'},endpoint=True)


if __name__=='__main__': unittest.main()
